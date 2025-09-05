import asyncio
import logging
import multiprocessing
import sys
import time
import traceback
import random
import argparse
from typing import List, Optional
from queue import Empty as QueueEmptyException

import colorlog
from dotenv import load_dotenv

from config import (
    LOGGING_LEVEL,
    THIRD_PARTY_LOGGING_LEVEL,
    SYSTEM_AGENTS_FILE,
    KNOWLEDGE_FILE,
    MAX_CHILD_RESTARTS,
)
from git_utils import (
    get_git_repo,
    git_commit_files,
    git_get_current_commit_hash,
    git_tag_commit,
    git_rollback_files,
    git_get_tag_message,
)

# Load environment variables from .env file
load_dotenv()

# Configure logging with color
handler = colorlog.StreamHandler()
handler.setFormatter(
    colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )
)

# Configure root logger explicitly to override any library settings
root_logger = logging.getLogger()
root_logger.setLevel(LOGGING_LEVEL)

# Clear any existing handlers and add our colored handler
if root_logger.hasHandlers():
    root_logger.handlers.clear()
root_logger.addHandler(handler)

# Get the main orchestrator logger and set its level explicitly
logger = logging.getLogger("MainOrchestrator")
logger.setLevel(LOGGING_LEVEL)

# Suppress verbose logs from third-party libraries based on the .env setting
third_party_loggers = [
    "httpcore",
    "httpx",
    "google_adk",
    "google_genai",
    "git",
    "asyncio",
]
for lib_name in third_party_loggers:
    logging.getLogger(lib_name).setLevel(THIRD_PARTY_LOGGING_LEVEL)

logger.info(f"Application logging level set to {LOGGING_LEVEL}")
logger.info(f"Third-party library logging level set to {THIRD_PARTY_LOGGING_LEVEL}")


# --- Child Process Target Function ---
def child_process_target(ipc_queue: multiprocessing.Queue):
    """
    This function is run by the child process.
    It imports and runs the ADK agent loop from system_agents.py.
    """
    logger.info("Child Process: Started.")
    try:
        # Ensure system_agents can be imported (it's in the same directory)
        # If system_agents.py has issues, this import will fail.
        import system_agents

        logger.info("Child Process: system_agents.py imported successfully.")
        # The main logic from system_agents.py
        asyncio.run(system_agents.child_process_main(ipc_queue))
        logger.info("Child Process: ADK loop completed.")
    except ImportError as e:
        logger.error(
            f"Child Process: Failed to import system_agents.py. Error: {e}",
            exc_info=True,
        )
        ipc_queue.put(
            {
                "type": "critical_error",
                "message": f"ImportError in child: {e}",
                "details": traceback.format_exc(),
            }
        )
    except Exception as e:
        logger.error(
            f"Child Process: Unhandled exception in ADK loop. Error: {e}",
            exc_info=True,
        )
        ipc_queue.put(
            {
                "type": "critical_error",
                "message": f"Unhandled exception in child: {e}",
                "details": traceback.format_exc(),
            }
        )
    finally:
        logger.info("Child Process: Exiting.")


# --- Main Orchestrator Logic ---
import json
import os

class MainOrchestrator:
    def __init__(self, run_once=False):
        """Initializes the MainOrchestrator."""
        self.run_once = run_once
        self.child_process: Optional[multiprocessing.Process] = None
        self.ipc_queue: multiprocessing.Queue = multiprocessing.Queue()
        self.current_commit_hash: Optional[str] = None
        self.last_good_commit_hash: Optional[str] = None
        self.restart_count = 0
        self.repo = get_git_repo()
        self.state_file = ".orchestrator_state.json"
        self._load_state()

        # Initial commit of agent files if they exist and are not yet committed
        # This helps establish a baseline.
        initial_files_to_commit = []
        if SYSTEM_AGENTS_FILE.exists():
            initial_files_to_commit.append(SYSTEM_AGENTS_FILE)
        if KNOWLEDGE_FILE.exists():
            initial_files_to_commit.append(KNOWLEDGE_FILE)
        if initial_files_to_commit:
            if git_commit_files(initial_files_to_commit, "Initial state of agent files"):
                self.last_good_commit_hash = git_get_current_commit_hash()
                logger.info(
                    f"Initial commit successful. Last good commit: {self.last_good_commit_hash}"
                )
                self._save_state()

    def _save_state(self):
        """Saves the orchestrator's state to a file."""
        state = {
            "last_good_commit_hash": self.last_good_commit_hash,
            "current_commit_hash": self.current_commit_hash,
            "restart_count": self.restart_count,
        }
        with open(self.state_file, "w") as f:
            json.dump(state, f)

    def _load_state(self):
        """Loads the orchestrator's state from a file."""
        if os.path.exists(self.state_file):
            with open(self.state_file, "r") as f:
                state = json.load(f)
            self.last_good_commit_hash = state.get("last_good_commit_hash")
            self.current_commit_hash = state.get("current_commit_hash")
            self.restart_count = state.get("restart_count", 0)
            logger.info("Orchestrator state loaded.")

    def _list_agent_tags(self) -> List[str]:
        """Lists all agent archive tags."""
        if not self.repo:
            return []
        return [
            tag.name
            for tag in self.repo.tags
            if tag.name.startswith("agent-archive-")
        ]

    def _get_performance_from_tag(self, tag_name: str) -> float:
        """Parses performance score from tag message."""
        message = git_get_tag_message(tag_name)
        if not message:
            return 0.0
        # This is a placeholder implementation. A more robust solution would
        # parse a structured message, e.g., JSON.
        try:
            # Example message: "Agent self-modification: system_agents.py. Performance: 0.85"
            performance_str = message.split("Performance:")[1].strip()
            return float(performance_str)
        except (IndexError, ValueError):
            return 0.0

    def _select_parent_agent(self) -> Optional[str]:
        """Selects a parent agent from the archive."""
        tags = self._list_agent_tags()
        if not tags:
            logger.info("No agent tags found, starting from current state.")
            return None

        # This is a simplified selection logic. A more advanced implementation
        # would use the formula from the DGM paper.
        # For now, we'll do a weighted random selection based on performance.
        weights = [self._get_performance_from_tag(tag) for tag in tags]

        # Add a small base weight to allow selection of zero-performance agents
        weights = [w + 0.1 for w in weights]

        try:
            selected_tag = random.choices(tags, weights=weights, k=1)[0]
            logger.info(f"Selected parent agent tag: {selected_tag}")
            return selected_tag
        except IndexError:
            return None

    def start_child_process(self, tag_name: Optional[str] = None):
        """
        Checks out the specified agent version and starts the child process.
        If tag_name is None, it runs from the current state.
        """
        if self.child_process and self.child_process.is_alive():
            logger.warning("Child process already running. Not starting another.")
            return

        if tag_name:
            logger.info(f"Checking out agent version: {tag_name}")
            files_to_checkout = [SYSTEM_AGENTS_FILE, KNOWLEDGE_FILE]
            if not git_rollback_files(files_to_checkout, tag_name):
                logger.error(
                    f"Failed to checkout tag {tag_name}. Aborting child process start."
                )
                return

        logger.info("Main Orchestrator: Starting child ADK process...")
        try:
            # Ensure system_agents.py exists before trying to run it
            if not SYSTEM_AGENTS_FILE.exists():
                logger.error(
                    f"{SYSTEM_AGENTS_FILE} not found. Cannot start child process."
                )
                # Potentially create a dummy if PRD implies it should always exist
                # For now, error out.
                return

            self.child_process = multiprocessing.Process(
                target=child_process_target,
                args=(self.ipc_queue,),
            )
            self.child_process.start()
            logger.info(f"Child process started with PID: {self.child_process.pid}")
            self.current_commit_hash = (
                git_get_current_commit_hash()
            )
            if not self.last_good_commit_hash:
                self.last_good_commit_hash = self.current_commit_hash
            self.restart_count = 0
            self._save_state()
        except Exception as e:
            logger.error(f"Failed to start child process: {e}", exc_info=True)
            self.child_process = None

    def _handle_modification_complete(self, message: dict):
        file_path = message.get("file_path")
        status = message.get("status")
        logger.info(
            f"Child reported modification of {file_path} with status: {status}"
        )

        files_to_commit = []
        if SYSTEM_AGENTS_FILE.exists():
            files_to_commit.append(SYSTEM_AGENTS_FILE)
        if KNOWLEDGE_FILE.exists():
            files_to_commit.append(KNOWLEDGE_FILE)

        if files_to_commit:
            commit_message = f"System self-modification. Executor updated: {file_path}. Learner may have updated knowledge.md."
            if git_commit_files(files_to_commit, commit_message):
                self.last_good_commit_hash = git_get_current_commit_hash()
                logger.info(
                    f"Successfully committed changes. New last good commit: {self.last_good_commit_hash}"
                )
                self._save_state()
                tag_name = f"agent-archive-{time.strftime('%Y%m%d-%H%M%S')}"
                git_tag_commit(tag_name, f"Agent self-modification: {file_path}")
            else:
                logger.error(
                    "Failed to commit changes after modification. Potential desync."
                )

        if status == "success_reload_requested":
            logger.info(
                "Reload requested by child. Terminating and restarting child process."
            )
            self.terminate_child_process()
            self.start_child_process()

    def _handle_critical_error(self, message: dict):
        error_message = message.get("message", "Unknown error")
        details = message.get("details", "No details")
        logger.error(
            f"Child reported critical error: {error_message}\nDetails:\n{details}"
        )
        self.handle_child_failure()

    def _handle_task_outcome(self, message: dict):
        status = message.get("status", "unknown")
        summary = message.get("output_summary", {})
        logger.info(
            f"Child reported task outcome: Status={status}. Summary: {summary}"
        )
        if KNOWLEDGE_FILE.exists():
            if git_commit_files(
                [KNOWLEDGE_FILE],
                f"Task Outcome: Status {status}. See knowledge.md for analysis.",
            ):
                self.last_good_commit_hash = git_get_current_commit_hash()
                logger.info(
                    f"Successfully committed knowledge.md. New last good commit: {self.last_good_commit_hash}"
                )
                self._save_state()
                tag_name = f"task-complete-{time.strftime('%Y%m%d-%H%M%S')}"
                git_tag_commit(tag_name, f"Task outcome: {status}")
            else:
                logger.warning("Failed to commit knowledge.md after task outcome.")
        logger.info(
            "Child process completed its run normally (no reload requested)."
        )

    def handle_child_message(self, message: dict):
        """
        Handles messages received from the child process via the IPC queue.

        Args:
            message: The message dictionary received from the child.
        """
        msg_type = message.get("type")
        logger.info(f"Main Orchestrator: Received message from child: {msg_type}")
        logger.debug(f"Full message: {message}")

        handlers = {
            "modification_complete": self._handle_modification_complete,
            "critical_error": self._handle_critical_error,
            "task_outcome": self._handle_task_outcome,
        }

        handler = handlers.get(msg_type)
        if handler:
            handler(message)
        else:
            logger.warning(f"Received unknown message type from child: {msg_type}")

    def _rollback_to_last_good_commit(self):
        if (
            self.last_good_commit_hash
            and self.last_good_commit_hash != self.current_commit_hash
        ):
            logger.warning(
                f"Attempting rollback to last good commit: {self.last_good_commit_hash}"
            )
            files_to_rollback = [
                SYSTEM_AGENTS_FILE,
                KNOWLEDGE_FILE,
            ]
            if git_rollback_files(files_to_rollback, self.last_good_commit_hash):
                logger.info("Rollback successful.")
                try:
                    with KNOWLEDGE_FILE.open("a", encoding="utf-8") as kf:
                        kf.write(
                            f"\n\n## ROLLBACK EVENT\n- Timestamp: {time.asctime()}\n"
                            f"- Rolled back from potentially problematic state after commit: {self.current_commit_hash}\n"
                            f"- Restored to commit: {self.last_good_commit_hash}\n"
                            f"- Reason: Child process failure or critical error.\n"
                        )
                    git_commit_files(
                        [KNOWLEDGE_FILE],
                        f"System Rollback: Logged failure and restored to {self.last_good_commit_hash[:7]}",
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to log rollback event to knowledge.md: {e}"
                    )
            else:
                logger.error("Rollback failed. System might be in an inconsistent state.")
                sys.exit(1)
        else:
            logger.warning(
                "No distinct last good commit to roll back to, or already at last good commit."
            )

    def handle_child_failure(self):
        """
        Handles critical failures in the child process, including rollback and restart.
        """
        logger.error("Child process failed or reported critical error.")
        self.restart_count += 1
        self._save_state()
        if self.run_once:
            logger.critical(
                "Child process failed during --run-once execution. Aborting."
            )
            sys.exit(1)
        if self.restart_count > MAX_CHILD_RESTARTS:
            logger.critical(
                f"Child process failed {self.restart_count} times. Max restarts reached. Aborting."
            )
            sys.exit(1)

        self._rollback_to_last_good_commit()

        logger.info(
            f"Restarting child process (Attempt {self.restart_count}/{MAX_CHILD_RESTARTS})."
        )
        self.terminate_child_process()
        self.start_child_process()

    def terminate_child_process(self):
        """Terminates the child process gracefully, with a fallback to a force kill."""
        if self.child_process and self.child_process.is_alive():
            logger.info(f"Terminating child process PID: {self.child_process.pid}...")
            # Send SIGTERM first for graceful shutdown
            self.child_process.terminate()
            try:
                self.child_process.join(timeout=10)  # Wait for graceful exit
                if self.child_process.is_alive():
                    logger.warning(
                        "Child process did not terminate gracefully, sending SIGKILL."
                    )
                    self.child_process.kill()  # Force kill
                    self.child_process.join(timeout=5)
            except Exception as e:
                logger.error(f"Error during child process termination: {e}")
        if self.child_process and not self.child_process.is_alive():
            logger.info("Child process terminated.")
        self.child_process = None

    def run(self):
        """
        The main run loop for the orchestrator.
        Orchestrates the evolutionary loop of parent selection, execution, and versioning.
        """
        logger.info("Main Orchestrator started. Press Ctrl+C to exit.")

        try:
            while True:  # Main evolutionary loop
                selected_tag = self._select_parent_agent()
                self.start_child_process(tag_name=selected_tag)

                # Wait for the child process to complete or fail
                while self.child_process and self.child_process.is_alive():
                    try:
                        message = self.ipc_queue.get(timeout=1.0)
                        self.handle_child_message(message)
                    except QueueEmptyException:
                        pass
                    time.sleep(0.1)

                # Post-run checks
                if self.child_process:  # If it was started
                    exit_code = self.child_process.exitcode
                    if exit_code != 0 and self.ipc_queue.empty():
                        logger.warning(
                            f"Child process exited unexpectedly with code: {exit_code}."
                        )
                        self.handle_child_failure()
                    else:
                        logger.info("Child process finished its run.")

                # Optional: Add a delay between evolutionary cycles
                time.sleep(5)
                if self.run_once:
                    logger.info(
                        " --run-once flag detected. Terminating after one iteration."
                    )
                    break

        except KeyboardInterrupt:
            logger.info("Ctrl+C received. Shutting down Main Orchestrator...")
        finally:
            self.terminate_child_process()
            logger.info("Main Orchestrator shut down.")


if __name__ == "__main__":
    # Ensure the script is run with multiprocessing support in mind for freezing
    multiprocessing.freeze_support()

    # Check if system_agents.py exists
    if not SYSTEM_AGENTS_FILE.exists():
        logger.critical(
            f"{SYSTEM_AGENTS_FILE} is missing. This file is essential for the child process."
        )
        logger.critical(
            "Please ensure system_agents.py is created, possibly by Roo or from a template."
        )
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Main Orchestrator for the Darwin Gödel Machine"
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run the orchestrator for a single iteration and then exit.",
    )
    args = parser.parse_args()
    logger.info("Starting Main Orchestrator...")
    orchestrator = MainOrchestrator(run_once=args.run_once)
    orchestrator.run()

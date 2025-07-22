import asyncio
import logging
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import List, Optional
from queue import Empty as QueueEmptyException

import git
from dotenv import load_dotenv
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError

# Load environment variables from .env file
load_dotenv()

# Configure logging
LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOGGING_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("MainOrchestrator")
logger.info(f"Logging level set to {LOGGING_LEVEL}")

# --- Configuration ---
SYSTEM_AGENTS_FILE = Path("system_agents.py")
KNOWLEDGE_FILE = Path("knowledge.md")
INPUT_FILE = Path("input.md") # Though child process reads this directly
GIT_COMMIT_USER_NAME = os.getenv("GIT_COMMIT_USER_NAME", "AdaptiveAgentSystem")
GIT_COMMIT_USER_EMAIL = os.getenv("GIT_COMMIT_USER_EMAIL", "agent@example.com")
MAX_CHILD_RESTARTS = 3 # Max restarts before giving up on a failed state
CHILD_PROCESS_TIMEOUT_SECONDS = 300 # Timeout for child process operations

# --- Git Helper Functions ---
def get_git_repo() -> Optional[git.Repo]:
    """Gets the Git repository object."""
    try:
        return git.Repo(Path("."), search_parent_directories=True)
    except (InvalidGitRepositoryError, NoSuchPathError):
        logger.info("No .git directory found. Initializing Git repository...")
        try:
            repo = git.Repo.init(Path("."))
            with repo.config_writer() as config:
                config.set_value("user", "name", GIT_COMMIT_USER_NAME)
                config.set_value("user", "email", GIT_COMMIT_USER_EMAIL)
            logger.info("Git repository initialized and user configured.")
            if Path(".gitignore").exists():
                repo.index.add([".gitignore"])
                repo.index.commit("Initial commit with .gitignore")
            return repo
        except GitCommandError as e:
            logger.error(f"Failed to initialize Git repository: {e}")
            return None
    except Exception as e:
        logger.error(f"Error getting Git repository: {e}")
        return None

def git_commit_files(files: List[Path], message: str) -> bool:
    """Adds and commits specified files."""
    repo = get_git_repo()
    if not repo:
        return False
    try:
        repo.index.add([str(f) for f in files])
        repo.index.commit(message)
        logger.info(f"Committed {files} with message: {message}")
        return True
    except GitCommandError as e:
        logger.error(f"Failed to commit files: {e}")
        return False

def git_get_current_commit_hash() -> Optional[str]:
    """Gets the current commit hash."""
    repo = get_git_repo()
    if not repo:
        return None
    try:
        return repo.head.commit.hexsha
    except Exception as e:
        logger.error(f"Could not get current commit hash: {e}")
        return None

def git_tag_commit(tag_name: str, message: Optional[str] = None) -> bool:
    """Tags the current commit."""
    repo = get_git_repo()
    if not repo:
        return False
    try:
        repo.create_tag(tag_name, message=message)
        logger.info(f"Tagged current commit with: {tag_name}")
        return True
    except GitCommandError as e:
        logger.error(f"Failed to tag commit: {e}")
        return False

def git_rollback_files(files: List[Path], commit_hash_or_tag: str) -> bool:
    """Rolls back specified files to a given commit hash or tag."""
    repo = get_git_repo()
    if not repo:
        return False
    try:
        logger.warning(f"Rolling back {files} to commit/tag: {commit_hash_or_tag}")
        repo.git.checkout(commit_hash_or_tag, "--", *[str(f) for f in files])
        logger.info("Rollback successful.")
        return True
    except GitCommandError as e:
        logger.error(f"Rollback failed: {e}")
        return False

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
        logger.error(f"Child Process: Failed to import system_agents.py. Error: {e}", exc_info=True)
        ipc_queue.put({"type": "critical_error", "message": f"ImportError in child: {e}", "details": traceback.format_exc()})
    except Exception as e:
        logger.error(f"Child Process: Unhandled exception in ADK loop. Error: {e}", exc_info=True)
        ipc_queue.put({"type": "critical_error", "message": f"Unhandled exception in child: {e}", "details": traceback.format_exc()})
    finally:
        logger.info("Child Process: Exiting.")


# --- Main Orchestrator Logic ---
class MainOrchestrator:
    def __init__(self):
        self.child_process: Optional[multiprocessing.Process] = None
        self.ipc_queue: multiprocessing.Queue = multiprocessing.Queue()
        self.current_commit_hash: Optional[str] = None
        self.last_good_commit_hash: Optional[str] = None
        self.restart_count = 0

        get_git_repo()
        # Initial commit of agent files if they exist and are not yet committed
        # This helps establish a baseline.
        initial_files_to_commit = []
        if SYSTEM_AGENTS_FILE.exists(): initial_files_to_commit.append(SYSTEM_AGENTS_FILE)
        if KNOWLEDGE_FILE.exists(): initial_files_to_commit.append(KNOWLEDGE_FILE)
        if initial_files_to_commit:
            if git_commit_files(initial_files_to_commit, "Initial state of agent files"):
                self.last_good_commit_hash = git_get_current_commit_hash()
                logger.info(f"Initial commit successful. Last good commit: {self.last_good_commit_hash}")


    def start_child_process(self):
        if self.child_process and self.child_process.is_alive():
            logger.warning("Child process already running. Not starting another.")
            return

        logger.info("Main Orchestrator: Starting child ADK process...")
        try:
            # Ensure system_agents.py exists before trying to run it
            if not SYSTEM_AGENTS_FILE.exists():
                logger.error(f"{SYSTEM_AGENTS_FILE} not found. Cannot start child process.")
                # Potentially create a dummy if PRD implies it should always exist
                # For now, error out.
                return

            self.child_process = multiprocessing.Process(
                target=child_process_target, args=(self.ipc_queue,)
            )
            self.child_process.start()
            logger.info(f"Child process started with PID: {self.child_process.pid}")
            self.current_commit_hash = git_get_current_commit_hash() # Hash before child runs
            if not self.last_good_commit_hash: # If not set by initial commit
                 self.last_good_commit_hash = self.current_commit_hash
            self.restart_count = 0 # Reset restart count on successful start
        except Exception as e:
            logger.error(f"Failed to start child process: {e}", exc_info=True)
            self.child_process = None


    def handle_child_message(self, message: dict):
        msg_type = message.get("type")
        logger.info(f"Main Orchestrator: Received message from child: {msg_type}")
        logger.debug(f"Full message: {message}")

        if msg_type == "modification_complete":
            file_path = message.get("file_path")
            status = message.get("status")
            logger.info(f"Child reported modification of {file_path} with status: {status}")
            
            # Commit changes to system_agents.py and knowledge.md
            # The LearningAgent might update knowledge.md in the same cycle
            files_to_commit = []
            if SYSTEM_AGENTS_FILE.exists(): files_to_commit.append(SYSTEM_AGENTS_FILE)
            if KNOWLEDGE_FILE.exists(): files_to_commit.append(KNOWLEDGE_FILE)

            if files_to_commit:
                commit_message = f"System self-modification. Executor updated: {file_path}. Learner may have updated knowledge.md."
                if git_commit_files(files_to_commit, commit_message):
                    self.last_good_commit_hash = git_get_current_commit_hash()
                    logger.info(f"Successfully committed changes. New last good commit: {self.last_good_commit_hash}")
                    # Tag this commit as a milestone (optional)
                    # git_tag_commit(f"iteration-{self.last_good_commit_hash[:7]}-stable")
                else:
                    logger.error("Failed to commit changes after modification. Potential desync.")
            
            if status == "success_reload_requested":
                logger.info("Reload requested by child. Terminating and restarting child process.")
                self.terminate_child_process() # Graceful termination if possible
                self.start_child_process()

        elif msg_type == "critical_error":
            error_message = message.get("message", "Unknown error")
            details = message.get("details", "No details")
            logger.error(f"Child reported critical error: {error_message}\nDetails:\n{details}")
            self.handle_child_failure()
        
        elif msg_type == "task_outcome":
            status = message.get("status", "unknown")
            summary = message.get("output_summary", {})
            logger.info(f"Child reported task outcome: Status={status}. Summary: {summary}")
            # Commit knowledge.md after every successful task outcome to record learning.
            if KNOWLEDGE_FILE.exists():
                # A more robust solution would check if the file was actually modified.
                # For now, we commit it to ensure the LearningAgent's analysis is saved.
                if git_commit_files([KNOWLEDGE_FILE], f"Task Outcome: Status {status}. See knowledge.md for analysis."):
                    self.last_good_commit_hash = git_get_current_commit_hash()
                    logger.info(f"Successfully committed knowledge.md. New last good commit: {self.last_good_commit_hash}")
                else:
                    logger.warning("Failed to commit knowledge.md after task outcome.")

            # If loop completed normally, and no reload, we might just continue or wait for new input.md
            # For this PRD, the loop is internal to child, so child will exit or error.
            # If child exits cleanly without reload request, it means it finished its internal loops.
            logger.info("Child process completed its run normally (no reload requested).")
            # Depending on design, might restart for new input.md or terminate.
            # For now, assume it means the current objective is done.

        else:
            logger.warning(f"Received unknown message type from child: {msg_type}")

    def handle_child_failure(self):
        logger.error("Child process failed or reported critical error.")
        self.restart_count += 1
        if self.restart_count > MAX_CHILD_RESTARTS:
            logger.critical(f"Child process failed {self.restart_count} times. Max restarts reached. Aborting.")
            # Potentially notify admin or take other drastic actions
            sys.exit(1) # Exit orchestrator if child is unrecoverable

        if self.last_good_commit_hash and self.last_good_commit_hash != self.current_commit_hash:
            logger.warning(f"Attempting rollback to last good commit: {self.last_good_commit_hash}")
            files_to_rollback = [SYSTEM_AGENTS_FILE, KNOWLEDGE_FILE] # Rollback both
            if git_rollback_files(files_to_rollback, self.last_good_commit_hash):
                logger.info("Rollback successful.")
                # The LearningAgent should be informed about this rollback in the next run.
                # This could be done by writing to a status file or a specific section in knowledge.md
                # before committing the rollback.
                try:
                    with KNOWLEDGE_FILE.open("a", encoding="utf-8") as kf:
                        kf.write(f"\n\n## ROLLBACK EVENT\n- Timestamp: {time.asctime()}\n"
                                 f"- Rolled back from potentially problematic state after commit: {self.current_commit_hash}\n"
                                 f"- Restored to commit: {self.last_good_commit_hash}\n"
                                 f"- Reason: Child process failure or critical error.\n")
                    git_commit_files([KNOWLEDGE_FILE], f"System Rollback: Logged failure and restored to {self.last_good_commit_hash[:7]}")
                except Exception as e:
                    logger.error(f"Failed to log rollback event to knowledge.md: {e}")
            else:
                logger.error("Rollback failed. System might be in an inconsistent state.")
                # Critical error, might need manual intervention
                sys.exit(1)
        else:
            logger.warning("No distinct last good commit to roll back to, or already at last good commit.")

        logger.info(f"Restarting child process (Attempt {self.restart_count}/{MAX_CHILD_RESTARTS}).")
        self.terminate_child_process()
        self.start_child_process()


    def terminate_child_process(self):
        if self.child_process and self.child_process.is_alive():
            logger.info(f"Terminating child process PID: {self.child_process.pid}...")
            # Send SIGTERM first for graceful shutdown
            self.child_process.terminate()
            try:
                self.child_process.join(timeout=10) # Wait for graceful exit
                if self.child_process.is_alive():
                    logger.warning("Child process did not terminate gracefully, sending SIGKILL.")
                    self.child_process.kill() # Force kill
                    self.child_process.join(timeout=5)
            except Exception as e:
                logger.error(f"Error during child process termination: {e}")
        if self.child_process and not self.child_process.is_alive():
             logger.info("Child process terminated.")
        self.child_process = None


    def run(self):
        logger.info("Main Orchestrator started. Press Ctrl+C to exit.")
        self.start_child_process()

        try:
            while True:
                if self.child_process and not self.child_process.is_alive():
                    exit_code = self.child_process.exitcode
                    logger.warning(f"Child process exited unexpectedly with code: {exit_code}.")
                    # If queue is empty, it might have crashed before sending error.
                    # If it exited with 0, it might have completed its run without reload.
                    if exit_code != 0 and self.ipc_queue.empty(): # Assume crash if non-zero and no message
                        self.handle_child_failure()
                    elif exit_code == 0 and self.ipc_queue.empty():
                        logger.info("Child process exited cleanly (code 0) with no pending messages. Assuming completion of current objectives.")
                        # Decide if to restart for new objectives or terminate. For now, just log.
                        # Could implement a file watcher on input.md or a timer to re-check.
                        # For this PRD, a clean exit means it's done with its internal loops.
                        # We might want to restart it to pick up new input.md content.
                        logger.info("Restarting child process to check for new objectives in input.md...")
                        self.start_child_process()


                try:
                    message = self.ipc_queue.get(timeout=1.0) # Check for messages
                    self.handle_child_message(message)
                except QueueEmptyException: # Use imported exception
                    pass # No message, continue loop
                
                time.sleep(0.1) # Small delay to prevent busy-waiting

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
        logger.critical(f"{SYSTEM_AGENTS_FILE} is missing. This file is essential for the child process.")
        logger.critical("Please ensure system_agents.py is created, possibly by Roo or from a template.")
        sys.exit(1)
        
    orchestrator = MainOrchestrator()
    orchestrator.run()
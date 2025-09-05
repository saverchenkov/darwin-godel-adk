import logging
from pathlib import Path
from typing import List, Optional

import git
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError

from config import GIT_COMMIT_USER_EMAIL, GIT_COMMIT_USER_NAME

logger = logging.getLogger(__name__)


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


def git_get_tag_message(tag_name: str) -> Optional[str]:
    """Gets the message of a specific tag."""
    repo = get_git_repo()
    if not repo:
        return None
    try:
        tag = repo.tags[tag_name]
        return tag.tag.message
    except (KeyError, AttributeError):
        logger.warning(f"Could not find tag or message for tag: {tag_name}")
        return None

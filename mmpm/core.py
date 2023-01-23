#!/usr/bin/env python3
import os
import sys
import json
import shutil
import pathlib
import subprocess
import datetime
import requests
import mmpm.color
import mmpm.utils
import mmpm.consts
import mmpm.models
import getpass
import mmpm.mmpm
from mmpm.logger import MMPMLogger
from re import findall
from pathlib import Path, PosixPath
from mmpm.magicmirror.package import MagicMirrorPackage
from mmpm.utils import get_env
from bs4 import NavigableString, Tag, BeautifulSoup
from collections import defaultdict
from socket import gethostname, gethostbyname
from typing import List, Dict, Callable
from textwrap import fill, indent

logger = MMPMLogger.get_logger(__name__)


def check_for_mmpm_updates(automated=False) -> bool:
    '''
    Scrapes the main file of MMPM off the github repo, and compares the current
    version, versus the one available in the master branch. If there is a newer
    version, the user is prompted for an upgrade.

    Parameters:
        automated (bool): if True, an extra notification is printed to the screen for the user to see

    Returns:
        bool: True on success, False on failure
    '''

    cyan_application: str = f"{mmpm.color.normal_cyan('application')}"
    logger.info(f'Checking for newer version of MMPM. Current version: {mmpm.mmpm.__version__}')

    if automated:
        message: str = f"Checking {mmpm.color.normal_green('MMPM')} [{cyan_application}] ({mmpm.color.normal_magenta('automated')}) for updates"
    else:
        message = f"Checking {mmpm.color.normal_green('MMPM')} [{cyan_application}] for updates"

    mmpm.utils.plain_print(message)

    try:
        # just to keep the console output the same as all other update commands
        error_code, contents, _ = mmpm.utils.run_cmd(['curl', mmpm.consts.MMPM_FILE_URL])
    except KeyboardInterrupt:
        mmpm.utils.keyboard_interrupt_log()

    if error_code:
        mmpm.utils.fatal_msg('Failed to retrieve MMPM version number')

    version_number: float = float(findall(r"\d+\.\d+", findall(r"__version__ = \d+\.\d+", contents)[0])[0])
    print(mmpm.consts.GREEN_CHECK_MARK)

    if not version_number:
        mmpm.utils.fatal_msg('No version number found on MMPM repository')

    can_upgrade: bool = version_number > mmpm.mmpm.__version__

    if can_upgrade:
        logger.info(f'Found newer version of MMPM: {version_number}')
    else:
        logger.info(f'No newer version of MMPM found > {version_number} available. The current version is the latest')

    upgrades = get_available_upgrades()

    with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'w', encoding="utf-8") as available_upgrades:
        upgrades[mmpm.consts.MMPM] = can_upgrade
        json.dump(upgrades, available_upgrades, default=lambda pkg: pkg.serialize())

    return can_upgrade


def upgrade_available_packages_and_applications(assume_yes: bool = False, selection: List[str] = []) -> None:
    '''
    Wrapper method to handle upgrade process of all available packages and/or
    applications (MMPM and MagicMirror). A user may supply specific
    packages/applications to upgrade, or upgrade all available by supplying no
    arguments. No result is returned. All sub-functions responsible for
    upgrading packages handle errors, and the execution does not need to halt
    do to errors in this wrapper method

    Parameters:
        assume_yes (bool): if True, the user prompt is skipped
        selection (List[str]): the specific list of packaes/application names provided by the user. This is optional

    Returns:
        None
    '''
    confirmed: dict = {mmpm.consts.PACKAGES: [], mmpm.consts.MMPM: False, mmpm.consts.MAGICMIRROR: False}
    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))
    upgrades = get_available_upgrades()
    upgraded: bool = False

    has_upgrades: bool = False
    mmpm_selected: bool = False
    magicmirror_selected: bool = False
    user_selections: bool = bool(selection)

    for key in upgrades[MMPM_MAGICMIRROR_ROOT]:
        if upgrades[MMPM_MAGICMIRROR_ROOT][key]:
            has_upgrades = True
            break

    if not has_upgrades and not upgrades[mmpm.consts.MMPM]:
        print(f'No upgrades available {mmpm.consts.YELLOW_X}')

    if mmpm.consts.MMPM in selection and upgrades[mmpm.consts.MMPM]:
        mmpm_selected = True
        selection.remove(mmpm.consts.MMPM)

    if upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES]:
        if selection:
            print(selection)
            valid_pkgs: List[MagicMirrorPackage] = [pkg for pkg in upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES] if pkg.title in selection]

            for pkg in upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES]:
                if pkg.title in selection:
                    valid_pkgs.append(pkg)
                    selection.remove(pkg.title)

            if mmpm.consts.MAGICMIRROR in selection and upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.MAGICMIRROR]:
                magicmirror_selected = True
                selection.remove(mmpm.consts.MAGICMIRROR)

            if selection: # the left overs that weren't matched
                mmpm.utils.error_msg(f'Unable to match {selection} to a package/application with available upgrades')

            for package in valid_pkgs:
                if package.title in selection and mmpm.utils.prompt_user(f'Upgrade {mmpm.color.normal_green(package.title)} ({package.repository}) now?', assume_yes=assume_yes):
                    confirmed[mmpm.consts.PACKAGES].append(package)
        else:
            for package in upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES]:
                if mmpm.utils.prompt_user(f'Upgrade {mmpm.color.normal_green(package.title)} ({package.repository}) now?', assume_yes=assume_yes):
                    confirmed[mmpm.consts.PACKAGES].append(package)

    if upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.MAGICMIRROR] and (magicmirror_selected or not user_selections):
        confirmed[mmpm.consts.MAGICMIRROR] = mmpm.utils.prompt_user(f"Upgrade {mmpm.color.normal_green('MagicMirror')} now?", assume_yes=assume_yes)

    if upgrades[mmpm.consts.MMPM] and (mmpm_selected or not user_selections):
        if mmpm.utils.get_env('MMPM_IS_DOCKER_IMAGE'):
            mmpm.utils.error_msg('Sorry, MMPM you will have upgrade MMPM by retrieving the latest Docker image when it is ready')
        else:
            mmpm.utils.warning_msg('Please upgrade MMPM using `pip3 install --user --upgrade mmpm`, followed by `mmpm install --gui`')

    for pkg in confirmed[mmpm.consts.PACKAGES]:
        error = pkg.upgrade()

        if error:
            mmpm.utils.error_msg(error)
            continue

        upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES].remove(pkg)
        upgraded = True

    if confirmed[mmpm.consts.MAGICMIRROR]:
        error = upgrade_magicmirror()

        if error:
            mmpm.utils.error_msg(error)
        else:
            upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.MAGICMIRROR] = False
            upgraded = True

    upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES] = [pkg.serialize_full() for pkg in upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES]]

    with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'w', encoding="utf-8") as available_upgrades:
        json.dump(upgrades, available_upgrades, default=lambda pkg: pkg.serialize())

    if upgraded and mmpm.utils.is_magicmirror_running():
        print('Restart MagicMirror for the changes to take effect')



def check_for_package_updates(packages: Dict[str, List[MagicMirrorPackage]]) -> List[MagicMirrorPackage]:
    '''
    Depending on flags passed in as arguments:

    Checks for available module updates, and alerts the user. Or, pulls latest
    version of module(s) from the associated repos.

    If upgrading, a user can upgrade all modules that have available upgrades
    by ommitting additional arguments. Or, upgrade specific modules by
    supplying their case-sensitive name(s) as an addtional argument.

    Parameters:
        packages (Dict[str, List[MagicMirrorPackage]]): Dictionary of MagicMirror modules

    Returns:
        upgradable (List[MagicMirrorPackage]): the list of packages that have available upgrades
    '''

    MMPM_MAGICMIRROR_ROOT: PosixPath = Path(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))
    MAGICMIRROR_MODULES_DIR: PosixPath = MMPM_MAGICMIRROR_ROOT / 'modules'

    if not MAGICMIRROR_MODULES_DIR.exists():
        mmpm.utils.env_variables_fatal_msg(f"'{str(MAGICMIRROR_MODULES_DIR)}' does not exist.")

    os.chdir(MAGICMIRROR_MODULES_DIR)
    installed_packages: Dict[str, List[MagicMirrorPackage]] = get_installed_packages(packages)
    any_installed: bool = False

    for package in installed_packages.values():
        if package:
            any_installed = True
            break

    if not any_installed:
        # asserting the available-updates file doesn't contain any artifacts of
        # previously installed packages that had updates at one point in time
        if not mmpm.utils.reset_available_upgrades_for_environment(MMPM_MAGICMIRROR_ROOT):
            logger.error('Failed to reset available upgrades for the current environment. File has been recreated')
            os.system(f'rm -f {mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE}; touch {mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE}')
        return []

    upgradable: List[MagicMirrorPackage] = []
    cyan_package: str = f"{mmpm.color.normal_cyan('package')}"

    for _packages in installed_packages.values():
        # mypy is incorrectly identifying an error here
        for package in _packages: # type: ignore
            os.chdir(package.directory) # type: ignore

            mmpm.utils.plain_print(f'Checking {mmpm.color.normal_green(package.title)} [{cyan_package}] for updates') # type: ignore

            try:
                error_code, _, stdout = mmpm.utils.run_cmd(['git', 'fetch', '--dry-run'])

            except KeyboardInterrupt:
                print(mmpm.consts.RED_X)
                mmpm.utils.keyboard_interrupt_log()

            if error_code:
                print(mmpm.consts.RED_X)
                mmpm.utils.error_msg('Unable to communicate with git server')
                continue

            if stdout:
                upgradable.append(package) # type: ignore

            print(mmpm.consts.GREEN_CHECK_MARK)

    upgrades: dict = get_available_upgrades()

    with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'w', encoding="utf-8") as available_upgrades:
        if MMPM_MAGICMIRROR_ROOT not in upgrades:
            upgrades[MMPM_MAGICMIRROR_ROOT] = {mmpm.consts.PACKAGES: [], mmpm.consts.MAGICMIRROR: False}

        upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES] = [pkg.serialize_full() for pkg in upgradable]
        json.dump(upgrades, available_upgrades, default=lambda pkg: pkg.serialize())

    return upgradable


def search_packages(packages: Dict[str, List[MagicMirrorPackage]], query: str, case_sensitive: bool = False, by_title_only: bool = False) -> Dict[str, List[MagicMirrorPackage]]:
    '''
    Used to search the 'modules' for either a category, or keyword/phrase
    appearing within module descriptions. If the argument supplied is a
    category name, all modules from that category will be listed. Otherwise,
    all modules whose descriptions contain the keyword/phrase will be
    displayed.

    Parameters:
        packages (Dict[str, List[MagicMirrorPackage]]): Dictionary of MagicMirror modules
        query (str): user provided search string
        case_sensitive (bool): if True, the query's exact casing is used in search
        by_title_only (bool): if True, only the title is considered when matching packages to query

    Returns:
        search_results (Dict[str, List[MagicMirrorPackage]]): the dictionary of packages, grouped by category that are search matches
    '''

    # if the query matches one of the category names exactly, return everything in that category
    if query in packages:
        return {query: packages[query]}

    search_results: Dict[str, List[MagicMirrorPackage]] = defaultdict(list)

    if by_title_only:
        match = lambda query, pkg: query == pkg.title
    elif case_sensitive:
        match = lambda query, pkg: query in pkg.description or query in pkg.title or query in pkg.author
    else:
        query = query.lower()
        match = lambda query, pkg: query in pkg.description.lower() or query in pkg.title.lower() or query in pkg.author.lower()

    for category, _packages in packages.items():
        search_results[category] = [package for package in _packages if match(query, package)]

    return search_results


def show_package_details(packages: Dict[str, List[MagicMirrorPackage]], remote: bool) -> None:
    '''
    Displays more detailed information that presented in normal search results.
    The output is formatted similarly to the output of the Debian/Ubunut 'apt' CLI

    Parameters:
        packages (List[defaultdict]): List of Categorized MagicMirror packages
        remote (bool): if True, extra detail is retrieved from the repository's API (GitHub, GitLab, or Bitbucket)

    Returns:
        None
    '''

    def __show_package__(category: str, package: MagicMirrorPackage) -> None:
        print(mmpm.color.normal_green(package.title))
        print(f'  Category: {category}')
        print(f'  Repository: {package.repository}')
        print(f'  Author: {package.author}')

    if not remote:
        def __show_details__(packages: dict) -> None:
            for category, _packages in packages.items():
                for package in _packages:
                    __show_package__(category, package)
                    print(indent(fill(f'Description: {package.description}\n', width=80), prefix='  '), '\n')

    else:
        def __show_details__(packages: dict) -> None:
            for category, _packages  in packages.items():
                for package in _packages:
                    __show_package__(category, package)
                    for key, value in mmpm.utils.get_remote_package_details(package).items():
                        print(f"  {key}: {value}")
                    print(indent(fill(f'Description: {package.description}\n', width=80), prefix='  '), '\n')

    __show_details__(packages)


def get_installation_candidates(packages: Dict[str, List[MagicMirrorPackage]], packages_to_install: List[str]) -> List[MagicMirrorPackage]:
    '''
    Used to display more detailed information that presented in normal search results

    Parameters:
        packages (Dict[str, List[MagicMirrorPackage]]): MagicMirror modules database
        packages_to_install (List[str]): list of modules provided by user through command line arguments

    Returns:
        installation_candidates (List[MagicMirrorPackage]): list of modules whose module names match those of the modules_to_install
    '''

    installation_candidates: List[MagicMirrorPackage] = []

    for package_to_install in packages_to_install:
        found: bool = False
        for category in packages.values():
            for package in category:
                if package.title == package_to_install:
                    logger.info(f'Matched {package.title} to installation candidate')
                    installation_candidates.append(package)
                    found = True
        if not found:
            mmpm.utils.error_msg(f"Unable to match package to query of '{package_to_install}'. Is there a typo?")

    return installation_candidates


def install_packages(installation_candidates: List[MagicMirrorPackage], assume_yes: bool = False) -> bool:
    '''
    Compares list of 'modules_to_install' to modules found within the
    'modules', clones the repository within the ~/MagicMirror/modules
    directory, and runs 'npm install' for each newly installed module.

    Parameters:
        installation_candidates (List[MagicMirrorPackage]): List of MagicMirrorPackages to install
        assume_yes (bool): if True, assume yes for user response, and do not display prompt

    Returns:
        success (bool): True upon success, False upon failure
    '''

    MAGICMIRROR_MODULES_DIR: PosixPath = Path(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV)) / 'modules'

    if not MAGICMIRROR_MODULES_DIR.exists():
        mmpm.utils.error_msg('MagicMirror directory not found. Please ensure the MMPM environment variables are set properly in your shell configuration')
        return False

    if not installation_candidates:
        mmpm.utils.error_msg('Unable to match query any to installation candidates')
        return False

    logger.info(f'Changing into MagicMirror modules directory {MAGICMIRROR_MODULES_DIR}')
    os.chdir(MAGICMIRROR_MODULES_DIR)

    # a flag to check if any of the modules have been installed. Used for displaying a message later
    match_count: int = len(installation_candidates)
    print(mmpm.color.normal_cyan(f"Matched query to {match_count} {'package' if match_count == 1 else 'packages'}"))

    for index, candidate in enumerate(installation_candidates):
        if not mmpm.utils.prompt_user(f'Install {mmpm.color.normal_green(candidate.title)} ({candidate.repository})?', assume_yes=assume_yes):
            logger.info(f'User not chose to install {candidate.title}')
            installation_candidates[index] = MagicMirrorPackage()
        else:
            logger.info(f'User chose to install {candidate.title} ({candidate.repository})')

    existing_module_dirs: List[str] = mmpm.utils.get_existing_package_directories()
    starting_count: int = len(existing_module_dirs)

    for package in installation_candidates:
        if package == None: # the module may be empty due to the above for loop
            continue

        package.directory = os.path.join(MAGICMIRROR_MODULES_DIR, package.title)

        for existing_dir in existing_module_dirs:
            if package.directory == existing_dir:
                logger.error(f'Conflict encountered. Found a package named {package.title} already at {package.directory}')
                mmpm.utils.error_msg(f'A module named {package.title} is already installed in {package.directory}. Please remove {package.title} first.')
                continue

        try:
            error: str = install_package(package, assume_yes=assume_yes)

            if not error:
                existing_module_dirs.append(package.title)

        except KeyboardInterrupt:
            logger.info(f'Cleaning up cancelled installation path of {package.directory} before exiting')
            os.chdir(mmpm.consts.HOME_DIR)
            os.system(f"rm -rf '{package.directory}'")
            mmpm.utils.keyboard_interrupt_log()

    if len(existing_module_dirs) == starting_count:
        return False

    print('Run `mmpm open --config` to edit the configuration for newly installed modules')
    return True


def install_package(package: MagicMirrorPackage, assume_yes: bool = False) -> str:
    '''
    Install a provided MagicMirror package. The package repository is cloned,
    and the helper methods to install dependencies are called. If the
    installation fails, the user is asked if they would like to remove the
    directory. They may decline if they would like to manually correct any
    encountered error.

    Parameters:
        package (MagicMirrorPackage): the MagicMirrorPackage to be installed
        assume_yes (bool): if True, all prompts are assumed to have a response of yes from the user

    Returns:
        error (str): empty string if installation was successful, otherwise the error message
    '''

    MAGICMIRROR_MODULES_DIR: str = os.path.normpath(os.path.join(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV), 'modules'))
    os.chdir(MAGICMIRROR_MODULES_DIR)

    print(f'{mmpm.consts.GREEN_PLUS} Installing {mmpm.color.normal_green(package.title)}')

    error_code, _, stderr = mmpm.utils.clone(
        package.title,
        package.repository,
        os.path.normpath(package.directory if package.directory else os.path.join(MAGICMIRROR_MODULES_DIR, package.title))
    )

    if error_code:
        print(mmpm.consts.RED_X)
        mmpm.utils.error_msg(stderr)
        return stderr

    print(mmpm.consts.GREEN_CHECK_MARK)
    error: str = mmpm.utils.install_dependencies(package.directory)
    os.chdir(MAGICMIRROR_MODULES_DIR)

    if error:
        mmpm.utils.error_msg(error)
        message: str = f"Failed to install {package.title} at '{package.directory}'"
        logger.error(message)

        yes = mmpm.utils.prompt_user(
            f"{mmpm.color.bright_red('ERROR:')} Failed to install {package.title} at '{package.directory}'. Remove the directory?",
            assume_yes=assume_yes
        )

        if yes:
            message = f"User chose to remove {package.title} at '{package.directory}'"
            # just to make sure there aren't any errors in removing the directory
            os.system(f"rm -rf '{package.directory}'")
            print(f"{mmpm.consts.GREEN_PLUS} Removing '{package.directory}' {mmpm.consts.GREEN_CHECK_MARK}")
        else:
            message = f"Keeping {package.title} at '{package.directory}'"
            print(f'\n{message}\n')
            logger.info(message)

        return error

    return ''


def check_for_magicmirror_updates() -> bool:
    '''
    Checks for updates available to the MagicMirror repository. Alerts user if an upgrade is available.

    Parameters:
        None

    Returns:
        bool: True upon success, False upon failure
    '''
    MMPM_MAGICMIRROR_ROOT: PosixPath = Path(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))

    if not MMPM_MAGICMIRROR_ROOT.exists():
        mmpm.utils.error_msg('MagicMirror application directory not found. Please ensure the MMPM environment variables are set properly in your shell configuration')
        return False

    is_git: bool = True

    if not (MMPM_MAGICMIRROR_ROOT / '.git').exists():
        mmpm.utils.warning_msg('The MagicMirror root is not a git repo. If running MagicMirror as a Docker container, updates cannot be performed via mmpm.')
        is_git = False

    update_available: bool = False

    if is_git:
        os.chdir(MMPM_MAGICMIRROR_ROOT)
        cyan_application: str = f"{mmpm.color.normal_cyan('application')}"
        mmpm.utils.plain_print(f"Checking {mmpm.color.normal_green('MagicMirror')} [{cyan_application}] for updates")

        try:
            # stdout and stderr are flipped for git command output, because that totally makes sense
            # except now stdout doesn't even contain error messages...thanks git
            error_code, _, stdout = mmpm.utils.run_cmd(['git', 'fetch', '--dry-run'])
        except KeyboardInterrupt:
            print(mmpm.consts.RED_X)
            mmpm.utils.keyboard_interrupt_log()

        print(mmpm.consts.GREEN_CHECK_MARK)

        if error_code:
            mmpm.utils.error_msg('Unable to communicate with git server')

        if stdout:
            update_available = True

    upgrades: dict = {}

    with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'r', encoding="utf-8") as available_upgrades:
        try:
            upgrades = json.load(available_upgrades)
        except json.JSONDecodeError:
            upgrades = {
                mmpm.consts.MMPM: False,
                MMPM_MAGICMIRROR_ROOT: {mmpm.consts.PACKAGES: [], mmpm.consts.MAGICMIRROR: update_available}
            }

    with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'w', encoding="utf-8") as available_upgrades:
        if MMPM_MAGICMIRROR_ROOT not in upgrades:
            upgrades[MMPM_MAGICMIRROR_ROOT] = {mmpm.consts.PACKAGES: [], mmpm.consts.MAGICMIRROR: update_available}
        else:
            upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.MAGICMIRROR] = update_available

        json.dump(upgrades, available_upgrades, default=lambda pkg: pkg.serialize())

    return update_available


def upgrade_magicmirror() -> str:
    '''
    Handles upgrade processs of MagicMirror by pulling changes from MagicMirror
    repo, and installing dependencies.

    Parameters:
        None

    Returns:
        error (str): empty string if succcessful, contains error message on failure
    '''
    print(f"{mmpm.consts.GREEN_PLUS} Upgrading {mmpm.color.normal_green('MagicMirror')}")

    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))

    os.chdir(MMPM_MAGICMIRROR_ROOT)
    error_code, _, stderr = mmpm.utils.run_cmd(['git', 'pull'], progress=False)

    if error_code:
        mmpm.utils.error_msg(f'Failed to upgrade MagicMirror {mmpm.consts.RED_X}')
        mmpm.utils.error_msg(stderr)
        return stderr

    error: str = mmpm.utils.install_dependencies(MMPM_MAGICMIRROR_ROOT)

    if error:
        mmpm.utils.error_msg(error)
        return error

    print('Upgrade complete! Restart MagicMirror for the changes to take effect')
    return ''


def install_mmpm_gui(assume_yes: bool = False) -> None:
    '''
    Installs the MMPM GUI by configuring the required NGINX files bundled in
    the MMPM PyPI package. This asks the user for sudo permissions. The
    template config files are copied from the mmpm PyPI package, modified to
    contain the proper paths, then installed in the required system folders

    Parameters:
        assume_yes (bool): if True, all prompts are assumed to have a response of yes from the user. This is used only internally of the MMPM CLI


    Returns:
        None
    '''

    if not mmpm.utils.prompt_user('Are you sure you want to install the MMPM GUI? This requires sudo permission.', assume_yes=assume_yes):
        return

    if not shutil.which('nginx'):
        mmpm.utils.fatal_msg('NGINX is not in your $PATH. Please install `nginx-full` (Debian), `nginx-mainline` (Arch) or equivalent')

    sub_gunicorn: str = 'SUBSTITUTE_gunicorn'
    sub_user: str = 'SUBSTITUTE_user'
    user: str = getpass.getuser()

    gunicorn_executable: str = shutil.which('gunicorn')

    if not gunicorn_executable:
        mmpm.utils.fatal_msg('Gunicorn executable not found. Please ensure Gunicorn is installed and in your PATH')

    temp_etc: str = '/tmp/etc'

    shutil.rmtree(temp_etc, ignore_errors=True)
    shutil.copytree(mmpm.consts.MMPM_BUNDLED_ETC_DIR, temp_etc)

    temp_mmpm_service: str = f'{temp_etc}/systemd/system/mmpm.service'

    remove_mmpm_gui(hide_prompt=True)

    with open(temp_mmpm_service, 'r', encoding="utf-8") as original:
        config = original.read()

    with open(temp_mmpm_service, 'w', encoding="utf-8") as mmpm_service:
        subbed = config.replace(sub_gunicorn, gunicorn_executable)
        subbed = subbed.replace(sub_user, user)
        mmpm_service.write(subbed)

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Copying NGINX and SystemdD service configs ')

    os.system(f'''
        sudo mkdir -p /var/www/mmpm;
        sudo cp -r /tmp/etc /;
        sudo cp -r {mmpm.consts.MMPM_PYTHON_ROOT_DIR}/static /var/www/mmpm;
        sudo cp -r {mmpm.consts.MMPM_PYTHON_ROOT_DIR}/templates /var/www/mmpm;
    ''')

    print(mmpm.consts.GREEN_CHECK_MARK)

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Cleaning configuration files and resetting SystemdD daemons ')
    print(mmpm.consts.GREEN_CHECK_MARK)

    os.system('rm -rf /tmp/etc')

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Reloading SystemdD daemon ')
    daemon_reload = mmpm.utils.systemctl('daemon-reload')

    if daemon_reload.returncode != 0:
        print(mmpm.consts.RED_X)
        mmpm.utils.error_msg('Failed to reload SystemdD daemon. See `mmpm log` for details')
        logger.error(daemon_reload.stderr.decode('utf-8'))
    else:
        print(mmpm.consts.GREEN_CHECK_MARK)

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Enabling MMPM SystemdD daemon ')

    enable_mmpm_service = mmpm.utils.systemctl('enable', ['mmpm.service'])

    if enable_mmpm_service.returncode != 0:
        if logger_gui_install_error_and_prompt_for_removal(enable_mmpm_service, 'Failed to enable MMPM SystemD service'):
            remove_mmpm_gui()
        sys.exit(127)

    print(mmpm.consts.GREEN_CHECK_MARK)

    start_mmpm_service = mmpm.utils.systemctl('start', ['mmpm.service'])

    if start_mmpm_service.returncode != 0:
        if logger_gui_install_error_and_prompt_for_removal(start_mmpm_service, 'Failed to start MMPM SystemD service'):
            remove_mmpm_gui()
        sys.exit(127)

    link_nginx_conf = subprocess.run(['sudo', 'ln', '-sf', '/etc/nginx/sites-available/mmpm.conf', '/etc/nginx/sites-enabled'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if link_nginx_conf.returncode != 0:
        if logger_gui_install_error_and_prompt_for_removal(link_nginx_conf, 'Failed to create symbolic links for NGINX configuration'):
            remove_mmpm_gui()
        sys.exit(127)

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Restarting NGINX SystemD service ')
    restart_nginx = mmpm.utils.systemctl('restart', ['nginx'])

    if restart_nginx.returncode != 0:
        if logger_gui_install_error_and_prompt_for_removal(restart_nginx, 'Failed to restart NGINX SystemD service'):
            remove_mmpm_gui()
        sys.exit(127)

    print(mmpm.consts.GREEN_CHECK_MARK)

    print('MMPM GUI installed! See `mmpm list --gui-url` for the URI, or run `mmpm open --gui` to launch')


def install_mmpm_as_magicmirror_module(assume_yes: bool = False) -> str:
    '''
    Installs the MMPM javascript files to the user's MagicMirror modules
    directory. This should succeed, but will fail if permissions are not
    granted to create the necessary files. This most likely will only happen in
    the case of MagicMirror being a docker image, and the folders being owned
    by root.

    Parameters:
        assume_yes (bool): if True, all prompts are assumed to have a response of yes from the user

    Returns:
        error (str): empty if successful, contains error message if the installation failed
    '''

    if not mmpm.utils.prompt_user('Are you sure you want to install the MMPM module?', assume_yes=assume_yes):
        return ''

    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))
    MAGICMIRROR_MODULES_DIR: str = os.path.normpath(os.path.join(MMPM_MAGICMIRROR_ROOT, 'modules'))
    MMPM_MODULE_DIR: str = os.path.join(MAGICMIRROR_MODULES_DIR, 'mmpm')

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Creating MMPM module in MagicMirror modules directory ')

    try:
        pathlib.Path(MMPM_MODULE_DIR).mkdir(parents=True, exist_ok=True, mode=0o777)
        shutil.copyfile(f'{mmpm.consts.MMPM_JS_DIR}/mmpm.js', f'{MMPM_MODULE_DIR}/mmpm.js')
        shutil.copyfile(f'{mmpm.consts.MMPM_JS_DIR}/node_helper.js', f'{MMPM_MODULE_DIR}/node_helper.js')
    except OSError as error:
        print(mmpm.consts.RED_X)
        mmpm.utils.error_msg('Failed to create MMPM module. Is the directory owned by root?')
        logger.error(str(error))
        return str(error)

    print(mmpm.consts.GREEN_CHECK_MARK)
    print('Run `mmpm open --config` and append { module: "mmpm" } to the modules array, then restart MagicMirror if running')

    return ''


def remove_mmpm_gui(hide_prompt: bool = False) -> None:
    '''
    Removes all SystemD services and NGINX, SystemD, and static web files
    associated with the MMPM GUI. This requires sudo permission, and the user
    is prompted, letting them know this is the case. During any failures,
    verbose error messages are written to the log files, and the user is made
    known of the errors.

    Parameters:
        hide_prompt (bool): used when calling the `remove_mmpm_gui` function from within the
                            `install_mmpm_gui` function to clean up any possible conflicts

    Returns:
        None
    '''
    if not hide_prompt and not mmpm.utils.prompt_user('Are you sure you want to remove the MMPM GUI? This requires sudo permission.'):
        return

    INACTIVE: str = 'inactive\n'
    DISABLED: str = 'disabled\n'

    is_active = mmpm.utils.systemctl('is-active', ['mmpm.service'])

    if is_active.returncode == 0:
        mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Stopping MMPM SystemD service ')
        stopping = mmpm.utils.systemctl('stop', ['mmpm.service'])

        if stopping.returncode == 0:
            print(mmpm.consts.GREEN_CHECK_MARK)
        else:
            print(mmpm.consts.RED_X)
            mmpm.utils.error_msg('Failed to stop MMPM SystemD service. See `mmpm log` for details')
            logger.error(f"{stopping.stdout.decode('utf-8')}\n{stopping.stderr.decode('utf-8')}")

    elif is_active.stdout.decode('utf-8') == INACTIVE:
        print(f'{mmpm.consts.GREEN_PLUS} MMPM SystemD service not active, nothing to do {mmpm.consts.GREEN_CHECK_MARK}')

    is_enabled = mmpm.utils.systemctl('is-enabled', ['mmpm.service'])

    if is_enabled.returncode == 0:
        mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Disabling MMPM SystemD service ')
        disabling = mmpm.utils.systemctl('disable', ['mmpm.service'])

        if disabling.returncode == 0:
            print(mmpm.consts.GREEN_CHECK_MARK)
        else:
            print(mmpm.consts.RED_X)
            mmpm.utils.error_msg('Failed to disable MMPM SystemD service. See `mmpm log` for details')
            logger.error(f"{disabling.stdout.decode('utf-8')}\n{disabling.stderr.decode('utf-8')}")

    elif is_enabled.stdout.decode('utf-8') == DISABLED:
        print(f'{mmpm.consts.GREEN_PLUS} MMPM SystemD service not enabled, nothing to do {mmpm.consts.GREEN_CHECK_MARK}')

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Force removing NGINX and SystemD configs ')

    cmd: str = f"""
    sudo rm -f {mmpm.consts.MMPM_SYSTEMD_SERVICE_FILE};
    sudo rm -f {mmpm.consts.MMPM_NGINX_CONF_FILE};
    sudo rm -rf /var/www/mmpm;
    sudo rm -f /etc/nginx/sites-available/mmpm.conf;
    sudo rm -f /etc/nginx/sites-enabled/mmpm.conf;
    """

    print(mmpm.consts.GREEN_CHECK_MARK)

    os.system(cmd)

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Reloading SystemdD daemon ')
    daemon_reload = mmpm.utils.systemctl('daemon-reload')

    if daemon_reload.returncode != 0:
        print(mmpm.consts.RED_X)
        mmpm.utils.error_msg('Failed to reload SystemdD daemon. See `mmpm log` for details')
        logger.error(daemon_reload.stderr.decode('utf-8'))
    else:
        print(mmpm.consts.GREEN_CHECK_MARK)

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Restarting NGINX SystemD service ')
    restart_nginx = mmpm.utils.systemctl('restart', ['nginx'])

    if restart_nginx.returncode != 0:
        print(mmpm.consts.RED_X)
        mmpm.utils.error_msg('Failed to restart NGINX SystemdD daemon. See `mmpm log` for details')
        logger.error(restart_nginx.stderr.decode('utf-8'))
    else:
        print(mmpm.consts.GREEN_CHECK_MARK)

    print('MMPM GUI Removed!')


def install_magicmirror() -> bool:
    '''
    Installs MagicMirror. First checks if a MagicMirror installation can be
    found, and if one is found, prompts user to update the MagicMirror.
    Otherwise, searches for current version of NodeJS on the system. If one is
    found, the MagicMirror is then installed. If an old version of NodeJS is
    found, a newer version is installed before installing MagicMirror.

    Parameters:
        None

    Returns:
        bool: True upon succcess, False upon failure
    '''
    known_envs: List[str] = [env for env in get_available_upgrades() if env != 'mmpm']
    parent: str = mmpm.consts.HOME_DIR


    MMPM_MAGICMIRROR_ROOT: PosixPath = Path(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))

    if MMPM_MAGICMIRROR_ROOT.exists():
        mmpm.utils.warning_msg(f'MagicMirror appears to be installed already in {os.getcwd()}. Please provide a new destination for the MagicMirror installation')
        try:
            parent = os.path.abspath(
                os.path.normpath(
                    mmpm.utils.assert_valid_input("Absolute path to new installation location: ",
                        forbidden_responses=known_envs,
                        reason='matches a known MagicMirror environment')
                )
            )
        except KeyboardInterrupt:
            print()
            sys.exit(0)
    else:
        print(f'{mmpm.consts.GREEN_PLUS} Installing MagicMirror')
    if mmpm.utils.prompt_user(f"Use '{parent}' as the parent directory of the new MagicMirror installation?"):
        pathlib.Path(parent).mkdir(parents=True, exist_ok=True)
        os.chdir(parent)
    else:
        sys.exit(0)

    for cmd in ["git", "npm"]:
        if not shutil.which(cmd):
            mmpm.utils.fatal_msg(f"'{cmd}' command not found. Please install '{cmd}', then re-run mmpm install --magicmirror")

    print(mmpm.color.normal_cyan(f'Installing MagicMirror in {parent}/MagicMirror ...'))
    os.system(f"cd {parent} && git clone https://github.com/MichMich/MagicMirror && cd MagicMirror && npm run install-mm")

    print(mmpm.color.normal_green("\nRun 'mmpm mm-ctl --start' to start MagicMirror"))
    return True


def remove_packages(installed_packages: Dict[str, List[MagicMirrorPackage]], packages_to_remove: List[str], assume_yes: bool = False) -> bool:
    '''
    Gathers list of modules currently installed in the ~/MagicMirror/modules
    directory, and removes each of the modules from the folder, if modules are
    currently installed. Otherwise, the user is shown an error message alerting
    them no modules are currently installed.

    Parameters:
        installed_packages (Dict[str, List[MagicMirrorPackage]]): List of dictionary of MagicMirror packages
        packages_to_remove (List[str]): List of package names to remove
        assume_yes (bool): if True, all prompts are assumed to have a response of yes from the user

    Returns:
        bool: True upon success, False upon failure
    '''

    cancelled_removal: List[str] = []
    marked_for_removal: List[str] = []

    MAGICMIRROR_MODULES_DIR: str = os.path.join(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV), 'modules')

    package_dirs: List[str] = os.listdir(MAGICMIRROR_MODULES_DIR)

    try:
        for packages in installed_packages.values():
            for package in packages:
                dir_name = os.path.basename(package.directory)
                if dir_name in package_dirs and dir_name in packages_to_remove:
                    prompt: str = f'Would you like to remove {mmpm.color.normal_green(package.title)} ({package.directory})?'
                    if mmpm.utils.prompt_user(prompt, assume_yes=assume_yes):
                        marked_for_removal.append(dir_name)
                        logger.info(f'User marked {dir_name} for removal')
                    else:
                        cancelled_removal.append(dir_name)
                        logger.info(f'User chose not to remove {dir_name}')
    except KeyboardInterrupt:
        mmpm.utils.keyboard_interrupt_log()

    for title in packages_to_remove:
        if title not in marked_for_removal and title not in cancelled_removal:
            mmpm.utils.error_msg(f"'{title}' is not installed")
            logger.info(f"User attemped to remove {title}, but no module named '{title}' was found in {MAGICMIRROR_MODULES_DIR}")

    for dir_name in marked_for_removal:
        shutil.rmtree(dir_name)
        print(f'{mmpm.consts.GREEN_PLUS} Removed {mmpm.color.normal_green(dir_name)} {mmpm.consts.GREEN_CHECK_MARK}')
        logger.info(f'Removed {dir_name}')

    if marked_for_removal:
        print('Run `mmpm open --config` to delete associated configurations of any removed modules')

    return True


def load_packages(force_refresh: bool = False) -> Dict[str, List[MagicMirrorPackage]]:
    '''
    Reads in modules from the hidden database file  and checks if the file is
    out of date. If so, the modules are gathered again from the MagicMirror 3rd
    Party Modules wiki.

    Parameters:
        force_refresh (bool): Boolean flag to force refresh of the database

    Returns:
        packages (Dict[str, List[MagicMirrorPackage]]): dictionary of MagicMirror 3rd party modules
    '''

    packages: dict = {}

    db_file: PosixPath = mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_DB_FILE
    db_exists: bool = db_file.exists()  and bool(db_file.stat().st_size)
    ext_pkgs_file: str = mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE

    if db_exists:
        logger.info(f'Backing up database file as {mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_DB_FILE}.bak')

        shutil.copyfile(
            mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_DB_FILE,
            f'{mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_DB_FILE}.bak'
        )

        logger.info('Back up of database complete')

    # if the database has expired, or doesn't exist, get a new one
    if force_refresh or not db_exists:
        mmpm.utils.plain_print(
            f"{mmpm.consts.GREEN_PLUS} {'Refreshing' if db_exists else 'Initializing'} MagicMirror 3rd party packages database "
        )

        packages = retrieve_packages()

        if not packages:
            print(mmpm.consts.RED_X)
            mmpm.utils.error_msg(f'Failed to retrieve packages from {mmpm.consts.MAGICMIRROR_MODULES_URL}. Please check your internet connection.')

        # save the new database
        else:
            with open(db_file, 'w', encoding="utf-8") as db:
                json.dump(packages, db, default=lambda pkg: pkg.serialize())

            print(mmpm.consts.GREEN_CHECK_MARK)

    if not packages and db_exists:
        with open(db_file, 'r', encoding="utf-8") as db:
            packages = json.load(db)

            for category in packages:
                packages[category] = mmpm.utils.list_of_dict_to_list_of_magicmirror_packages(packages[category])

    if packages and os.path.exists(ext_pkgs_file) and bool(os.stat(ext_pkgs_file).st_size):
        packages.update(**load_external_packages())

    return packages


def load_external_packages() -> Dict[str, List[MagicMirrorPackage]]:
    '''
    Extracts the external packages from the JSON files stored in
    ~/.config/mmpm/mmpm-external-packages.json

    If no data is found, an empty dictionary is returned

    Parameters:
        None

    Returns:
        external_packages (Dict[str, List[MagicMirrorPackage]]): the list of manually added MagicMirror packages
    '''
    external_packages: List[MagicMirrorPackage] = []

    if bool(os.stat(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE).st_size):
        try:
            with open(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE, 'r', encoding="utf-8") as ext_pkgs:
                external_packages = mmpm.utils.list_of_dict_to_list_of_magicmirror_packages(json.load(ext_pkgs)[mmpm.consts.EXTERNAL_PACKAGES])
        except Exception:
            message = f'Failed to load data from {mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE}. Please examine the file, as it may be malformed and required manual corrective action.'
            mmpm.utils.warning_msg(message)
    else:
        with open(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE, mode= 'w', encoding="utf-8") as ext_pkgs:
            json.dump({mmpm.consts.EXTERNAL_PACKAGES: external_packages}, ext_pkgs)

    return {mmpm.consts.EXTERNAL_PACKAGES: external_packages}


def retrieve_packages() -> Dict[str, List[MagicMirrorPackage]]:
    '''
    Scrapes the MagicMirror 3rd Party Wiki for all packages listed by community members

    Parameters:
        None

    Returns:
        packages (Dict[str, List[MagicMirrorPackage]]): dictionary of MagicMirror 3rd party modules
    '''

    packages: Dict[str, List[MagicMirrorPackage]] = defaultdict(list)
    response: requests.Response = requests.Response()

    try:
        response = requests.get(mmpm.consts.MAGICMIRROR_MODULES_URL, timeout=10)
    except requests.exceptions.RequestException:
        print(mmpm.consts.RED_X)
        mmpm.utils.fatal_msg('Unable to retrieve MagicMirror modules. Is your internet connection up?')
        return {}

    soup = BeautifulSoup(response.text, 'html.parser')
    table_soup: list = soup.find_all('table')
    category_soup = soup.find_all(attrs={'class': 'markdown-body'})
    categories_soup = category_soup[0].find_all('h3')
    del categories_soup[0] # the General Advice section

    # the last entry of the html element contents contains the actual category name
    categories: list = [category.contents[-1] for category in categories_soup]

    # the first index is a row that literally says 'Title' 'Author' 'Description'
    tr_soup: list = [table.find_all('tr')[1:] for table in table_soup]

    try:
        for index, row in enumerate(tr_soup):
            for tag in row:
                table_data: list = tag.find_all('td')

                if table_data[0].contents[0].contents[0] == mmpm.consts.MMPM:
                    break

                packages[categories[index]].append(MagicMirrorPackage.from_raw_data(table_data))

    except Exception as error:
        mmpm.utils.fatal_msg(str(error))

    return packages



# TODO: all these functions really need to be part of a class, this is way too much repetition # pylint: disable=fixme
def display_magicmirror_modules_status() -> None:
    '''
    Parses the MagicMirror config file for the modules listed, and reports
    which modules are currently enabled. A module is considered disabled if the
    module explictly contains a 'disabled' flag with a 'true' value. Otherwise,
    the module is considered enabled.

    Parameters:
        None

    Returns:
        None
    '''

    import threading

    stop_thread_event = threading.Event()
    client = mmpm.utils.socketio_client_factory()

    countdown_thread = threading.Thread(
        target=mmpm.utils.background_timer_thread,
        args=(stop_thread_event, "stop", client)
    )

    MMPM_MAGICMIRROR_URI: str = mmpm.utils.get_env(mmpm.consts.MMPM_MAGICMIRROR_URI_ENV)

    @client.on('connect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def connect(): # pylint: disable=unused-variable
        logger.info('connected to MagicMirror websocket')
        client.emit('FROM_MMPM_APP_get_active_modules', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE, data=None)
        logger.info('emitted request for active modules to MMPM module')


    @client.event
    def connect_error(): # pylint: disable=unused-variable
        mmpm.utils.error_msg('Failed to connect to MagicMirror websocket. Is the MMPM_MAGICMIRROR_URI environment variable set properly?')


    @client.on('disconnect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def disconnect(): # pylint: disable=unused-variable
        logger.info('disconnected from MagicMirror websocket')


    @client.on('ACTIVE_MODULES', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def active_modules(data): # pylint: disable=unused-variable
        logger.info('received active modules from MMPM MagicMirror module')
        stop_thread_event.set()

        if not data:
            print(mmpm.consts.RED_X)
            mmpm.utils.error_msg('No data was received from the MagicMirror websocket. Is the MMPM_MAGICMIRROR_URI environment variable set properly?')
        else:
            print(mmpm.consts.GREEN_CHECK_MARK)

        # on rare occasions, the result is sent back twice, I suppose due to timing issues
        for module in [json_data for index, json_data in enumerate(data) if json_data not in data[index + 1:]]:
            print(f"{mmpm.color.normal_green(module['name'])}\n  hidden: {'true' if module['hidden'] else 'false'}\n  key: {module['index'] + 1}\n")

        mmpm.utils.socketio_client_disconnect(client)
        countdown_thread.join()

    logger.info(f"attempting to connect to '{mmpm.consts.MMPM_SOCKETIO_NAMESPACE}' namespace within MagicMirror websocket")
    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Sending request to MagicMirror for active modules ')

    try:
        countdown_thread.start()
        client.connect(MMPM_MAGICMIRROR_URI, namespaces=[mmpm.consts.MMPM_SOCKETIO_NAMESPACE])
    except (OSError, BrokenPipeError, Exception) as error:
        mmpm.utils.error_msg('Failed to connect to MagicMirror, closing socket. Is MagicMirror running?')
        logger.error(str(error))
        mmpm.utils.socketio_client_disconnect(client)


# TODO: all these functions really need to be part of a class, this is way too much repetition
def hide_magicmirror_modules(modules_to_hide: List[int]):
    '''
    Creates a connection to the websocket opened by MagicMirror, and through
    the MMPM module, the provided module names are looked up, and hidden.
    If the module is already hidden, the display doesn't change.

    Parameters:
        modules_to_hide (List[int]): the indices of the modules to hide

    Returns:
        None
    '''

    for module in modules_to_hide:
        if not isinstance(module, int):
            mmpm.utils.fatal_msg("Module key(s) must all be integers.")

    import threading

    stop_thread_event = threading.Event()
    client = mmpm.utils.socketio_client_factory()

    countdown_thread = threading.Thread(
        target=mmpm.utils.background_timer_thread,
        args=(stop_thread_event, "stop", client)
    )

    MMPM_MAGICMIRROR_URI: str = mmpm.utils.get_env(mmpm.consts.MMPM_MAGICMIRROR_URI_ENV)

    if not modules_to_hide:
        return

    @client.on('connect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def connect(): # pylint: disable=unused-variable
        logger.info('connected to MagicMirror websocket')
        client.emit('FROM_MMPM_APP_toggle_modules', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE, data={'directive': 'hide', 'modules': modules_to_hide})
        logger.info('emitted request to hide modules to MMPM module')


    @client.event
    def connect_error(): # pylint: disable=unused-variable
        mmpm.utils.error_msg('Failed to connect to MagicMirror websocket. Is the MMPM_MAGICMIRROR_URI environment variable set properly?')


    @client.on('disconnect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def disconnect(): # pylint: disable=unused-variable
        logger.info('disconnected from MagicMirror websocket')


    @client.on('MODULES_TOGGLED', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def modules_toggled(data): # pylint: disable=unused-variable
        logger.info('received toggled modules from MMPM MagicMirror module')
        stop_thread_event.set()

        if not data:
            print(mmpm.consts.RED_X)
            mmpm.utils.error_msg('Unable to find provided module(s)')
        else:
            print(mmpm.consts.GREEN_CHECK_MARK)

        mmpm.utils.socketio_client_disconnect(client)
        countdown_thread.join()

    logger.info(f"attempting to connect to '{mmpm.consts.MMPM_SOCKETIO_NAMESPACE}' namespace within MagicMirror websocket")
    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Sending request to MagicMirror to hide modules with keys: {modules_to_hide} ')

    try:
        countdown_thread.start()
        client.connect(MMPM_MAGICMIRROR_URI, namespaces=[mmpm.consts.MMPM_SOCKETIO_NAMESPACE])
    except (OSError, BrokenPipeError, Exception) as error:
        mmpm.utils.error_msg('Failed to connect to MagicMirror, closing socket. Is MagicMirror running?')
        logger.error(str(error))
        mmpm.utils.socketio_client_disconnect(client)


# TODO: all these functions really need to be part of a class, this is way too much repetition
def show_magicmirror_modules(modules_to_show: List[int]) -> None:
    '''
    Creates a connection to the websocket opened by MagicMirror, and through
    the MMPM module, the provided module names are looked up, and made visible.
    If the module is already visible, the display doesn't change.

    Parameters:
        modules_to_show (List[int]): the indices of the modules to make visible

    Returns:
        None
    '''

    for module in modules_to_show:
        if not isinstance(module, int):
            mmpm.utils.fatal_msg("Module key(s) must all be integers.")

    import threading

    stop_thread_event = threading.Event()
    client = mmpm.utils.socketio_client_factory()

    countdown_thread = threading.Thread(
        target=mmpm.utils.background_timer_thread,
        args=(stop_thread_event, "stop", client)
    )

    MMPM_MAGICMIRROR_URI: str = mmpm.utils.get_env(mmpm.consts.MMPM_MAGICMIRROR_URI_ENV)

    if not modules_to_show:
        return

    @client.on('connect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def connect(): # pylint: disable=unused-variable
        logger.info('connected to MagicMirror websocket')
        client.emit('FROM_MMPM_APP_toggle_modules', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE, data={'directive': 'show', 'modules': modules_to_show})
        logger.info('emitted request for show modules to MMPM module')


    @client.event
    def connect_error(): # pylint: disable=unused-variable
        mmpm.utils.error_msg('Failed to connect to MagicMirror websocket. Is the MMPM_MAGICMIRROR_URI environment variable set properly?')


    @client.on('disconnect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def disconnect(): # pylint: disable=unused-variable
        logger.info('disconnected from MagicMirror websocket')

    @client.on('MODULES_TOGGLED', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def modules_toggled(data): # pylint: disable=unused-variable
        logger.info('received toggled modules from MMPM MagicMirror module')
        stop_thread_event.set()

        if not data:
            print(mmpm.consts.RED_X)
            mmpm.utils.error_msg('Unable to find provided module(s)')
        else:
            print(mmpm.consts.GREEN_CHECK_MARK)

        mmpm.utils.socketio_client_disconnect(client)
        countdown_thread.join()

    logger.info(f"attempting to connect to '{mmpm.consts.MMPM_SOCKETIO_NAMESPACE}' namespace within MagicMirror websocket")
    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Sending request to MagicMirror to show modules with keys: {modules_to_show} ')

    try:
        countdown_thread.start()
        client.connect(MMPM_MAGICMIRROR_URI, namespaces=[mmpm.consts.MMPM_SOCKETIO_NAMESPACE])
    except (OSError, BrokenPipeError, Exception):
        mmpm.utils.error_msg('Failed to connect to MagicMirror, closing socket. Is MagicMirror running?')
        mmpm.utils.socketio_client_disconnect(client)


def get_web_interface_url() -> str:
    '''
    Parses the MMPM nginx conf file for the port number assigned to the web
    interface, and returns a string containing containing the host IP and
    assigned port.

    Parameters:
        None

    Returns:
        str: The URL of the MMPM web interface
    '''

    if not os.path.exists(mmpm.consts.MMPM_NGINX_CONF_FILE):
        mmpm.utils.fatal_msg('The MMPM NGINX configuration file does not appear to exist. Is the GUI installed?')

    # this value needs to be retrieved dynamically in case the user modifies the nginx conf
    with open(mmpm.consts.MMPM_NGINX_CONF_FILE, 'r', encoding="utf-8") as conf:
        mmpm_conf = conf.read()

    try:
        port: str = findall(r"listen\s?\d+", mmpm_conf)[0].split()[1]
    except IndexError:
        mmpm.utils.fatal_msg('Unable to retrieve the port number of the MMPM web interface')

    return f'http://{gethostbyname(gethostname())}:{port}'


def stop_magicmirror() -> bool:
    '''
    Stops MagicMirror using pm2, if found, otherwise the associated
    processes are killed

    Parameters:
       None

    Returns:
        success (bool): True if successful, False if failure
    '''

    process: str = ''
    command: List[str] = []

    MMPM_MAGICMIRROR_PM2_PROCESS_NAME: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_PM2_PROCESS_NAME_ENV)
    MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE_ENV)

    if MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE:
        logger.info(f'docker-compose file set as {MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE}')

    if MMPM_MAGICMIRROR_PM2_PROCESS_NAME:
        logger.info(f'pm2 process set as {MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE}')

    if shutil.which('pm2') and MMPM_MAGICMIRROR_PM2_PROCESS_NAME:
        command = ['pm2', 'stop', MMPM_MAGICMIRROR_PM2_PROCESS_NAME]
        process = 'pm2'

    elif shutil.which('docker-compose') and MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE:
        command = ['docker-compose', '-f', MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE, 'stop']
        process = 'docker-compose'

    if command and process:
        mmpm.utils.plain_print(f"{mmpm.consts.GREEN_PLUS} stopping MagicMirror using {command[0]} ")
        logger.info(f"Using '{process}' to stop MagicMirror")
        # pm2 and docker-compose cause the output to flip
        error_code, stderr, _ = mmpm.utils.run_cmd(command, progress=False)

        if error_code:
            print(mmpm.consts.RED_X)
            mmpm.utils.env_variables_error_msg(stderr.strip())
            return False

        logger.info(f"stopped MagicMirror using '{process}'")
        print(mmpm.consts.GREEN_CHECK_MARK)
        return True

    mmpm.utils.kill_magicmirror_processes()
    return True


def start_magicmirror() -> bool:
    '''
    Launches MagicMirror using pm2, if found, otherwise a 'npm start' is run as
    a background process

    Parameters:
       None

    Returns:
        None
    '''
    logger.info('Starting MagicMirror')

    process: str = ''
    command: List[str] = []

    MMPM_MAGICMIRROR_PM2_PROCESS_NAME: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_PM2_PROCESS_NAME_ENV)
    MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE_ENV)

    if MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE:
        logger.info(f'docker-compose file set as {MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE}')

    if MMPM_MAGICMIRROR_PM2_PROCESS_NAME:
        logger.info(f'pm2 process set as {MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE}')

    if shutil.which('pm2') and MMPM_MAGICMIRROR_PM2_PROCESS_NAME:
        command = ['pm2', 'start', MMPM_MAGICMIRROR_PM2_PROCESS_NAME]
        process = 'pm2'

    elif shutil.which('docker-compose') and MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE:
        command = ['docker-compose', '-f', MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE, 'up', '-d']
        process = 'docker-compose'

    if command and process:
        mmpm.utils.plain_print(f"{mmpm.consts.GREEN_PLUS} starting MagicMirror using {command[0]} ")
        logger.info(f"Using '{process}' to start MagicMirror")
        error_code, stderr, _ = mmpm.utils.run_cmd(command, progress=False)

        if error_code:
            print(mmpm.consts.RED_X)
            mmpm.utils.env_variables_error_msg(stderr.strip())
            return False

        logger.info(f"started MagicMirror using '{process}'")
        print(mmpm.consts.GREEN_CHECK_MARK)
        return True

    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))

    os.chdir(MMPM_MAGICMIRROR_ROOT)
    logger.info("Running 'npm start' in the background")

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} npm start ')
    os.system('npm start &')
    print(mmpm.consts.GREEN_CHECK_MARK)
    logger.info("Using 'npm start' to start MagicMirror. Stdout/stderr capturing not possible in this case")
    return True


def restart_magicmirror() -> bool:
    '''
    Restarts MagicMirror using pm2, if found, otherwise the associated
    processes are killed and 'npm start' is re-run a background process

    Parameters:
       None

    Returns:
        None
    '''

    process: str = ''
    command: List[str] = []

    MMPM_MAGICMIRROR_PM2_PROCESS_NAME: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_PM2_PROCESS_NAME_ENV)
    MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE_ENV)

    if MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE:
        logger.info(f'docker-compose file set as {MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE}')

    if MMPM_MAGICMIRROR_PM2_PROCESS_NAME:
        logger.info(f'pm2 process set as {MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE}')

    if shutil.which('pm2') and MMPM_MAGICMIRROR_PM2_PROCESS_NAME:
        command = ['pm2', 'restart', MMPM_MAGICMIRROR_PM2_PROCESS_NAME]
        process = 'pm2'

    elif shutil.which('docker-compose') and MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE:
        command = ['docker-compose', '-f', MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE, 'restart']
        process = 'docker-compose'

    if command and process:
        mmpm.utils.plain_print(f"{mmpm.consts.GREEN_PLUS} restarting MagicMirror using {command[0]} ")
        logger.info(f"Using '{process}' to restart MagicMirror")

        # pm2 and docker-compose cause the output to flip
        error_code, stderr, _ = mmpm.utils.run_cmd(command, progress=False)

        if error_code:
            print(mmpm.consts.RED_X)
            mmpm.utils.env_variables_error_msg(stderr.strip())
            return False

        logger.info(f"restarted MagicMirror using '{process}'")
        print(mmpm.consts.GREEN_CHECK_MARK)
        return True

    if not stop_magicmirror():
        logger.error('Failed to stop MagicMirror using npm commands')
        return False

    if not start_magicmirror():
        logger.error('Failed to start MagicMirror using npm commands')
        return False

    logger.info('Restarted MagicMirror using npm commands')
    return True


def display_log_files(cli_logs: bool = False, gui_logs: bool = False, tail: bool = False) -> None:
    '''
    Displays contents of log files to stdout. If the --tail option is supplied,
    log contents will be displayed in real-time

    Parameters:
       cli_logs (bool): if True, the CLI log files will be displayed
       gui_logs (bool): if True, the Gunicorn log files for the web interface will be displayed
       tail (bool): if True, the contents will be displayed in real time

    Returns:
        None
    '''
    logs: List[str] = []

    if cli_logs:
        if mmpm.consts.MMPM_CLI_LOG_FILE.exists():
            logs.append(str(mmpm.consts.MMPM_CLI_LOG_FILE))
        else:
            mmpm.utils.error_msg('MMPM log file not found')

    if gui_logs:
        if mmpm.consts.MMPM_NGINX_ACCESS_LOG_FILE.exists():
            logs.append(str(mmpm.consts.MMPM_NGINX_ACCESS_LOG_FILE))
        else:
            mmpm.utils.error_msg('Gunicorn access log file not found')
        if mmpm.consts.MMPM_NGINX_ERROR_LOG_FILE.exists():
            logs.append(str(mmpm.consts.MMPM_NGINX_ERROR_LOG_FILE))
        else:
            mmpm.utils.error_msg('Gunicorn error log file not found')

    if logs:
        os.system(f"{'tail -F' if tail else 'cat'} {' '.join(logs)}")


def display_mmpm_env_vars() -> None:
    '''
    Displays the environment variables associated with MMPM, as well as their
    current value. A user may modify these values by setting them in their
    shell configuration file

    Parameters:
        None

    Returns:
        None
    '''

    logger.info('User listing environment variables, set with the following values')

    from pygments import highlight, formatters
    from pygments.lexers.data import JsonLexer

    with open(mmpm.consts.MMPM_ENV_FILE, 'r', encoding="utf-8") as env:
        print(highlight(json.dumps(json.load(env), indent=2), JsonLexer(), formatters.TerminalFormatter()))

    print('Run `mmpm open --env` to edit the variable values')


def install_autocompletion(assume_yes: bool = False) -> None:
    '''
    Adds autocompletion configuration to a user's shell configuration file.
    Detects configuration files for bash, zsh, fish, and tcsh

    Parameters:
        assume_yes (bool): if True, assume yes for user response, and do not display prompt

    Returns:
        None
    '''

    if not mmpm.utils.prompt_user('Are you sure you want to install the autocompletion feature for the MMPM CLI?', assume_yes=assume_yes):
        logger.info('User cancelled installation of autocompletion for MMPM CLI')
        return

    logger.info('user attempting to install MMPM autocompletion')
    shell: str = os.environ['SHELL']

    logger.info(f'detected user shell to be {shell}')

    autocomplete_url: str = 'https://github.com/kislyuk/argcomplete#activating-global-completion'
    error_message: str = f'Please see {autocomplete_url} for help installing autocompletion'

    complete_message = lambda config: f'Autocompletion installed. Please source {config} for the changes to take effect' # pylint: disable=unnecessary-lambda-assignment
    failed_match_message = lambda shell, configs: f'Unable to locate {shell} configuration file (looked for {configs}). {error_message}' # pylint: disable=unnecessary-lambda-assignment

    def __match_shell_config__(configs: List[str]) -> str:
        logger.info(f'searching for one of the following shell configuration files {configs}')
        for config in configs:
            config = mmpm.consts.HOME_DIR / config
            if config.exists():
                logger.info(f'found {str(config)} shell configuration file for {shell}')
                return config
        return ''

    def __echo_and_eval__(command: str) -> None:
        logger.info(f'executing {command} to install autocompletion')
        print(f'{mmpm.consts.GREEN_PLUS} {command}')
        os.system(command)

    if 'bash' in shell:
        files = ['.bashrc', '.bash_profile', '.bash_login', '.profile']
        config = __match_shell_config__(files)

        if not config:
            mmpm.utils.fatal_msg(failed_match_message('bash', files))

        __echo_and_eval__(f'echo \'eval "$(register-python-argcomplete mmpm)"\' >> {config}')

        print(complete_message(config))

    elif 'zsh' in shell:
        files = ['.zshrc', '.zprofile', '.zshenv', '.zlogin', '.profile']
        config = __match_shell_config__(files)

        if not config:
            mmpm.utils.fatal_msg(failed_match_message('zsh', files))

        __echo_and_eval__(f"echo 'autoload -U bashcompinit' >> {config}")
        __echo_and_eval__(f"echo 'bashcompinit' >> {config}")
        __echo_and_eval__(f'echo \'eval "$(register-python-argcomplete mmpm)"\' >> {config}')

        print(complete_message(config))

    elif 'tcsh' in shell:
        files = ['.tcshrc', '.cshrc', '.login']
        config = __match_shell_config__(files)

        if not config:
            mmpm.utils.fatal_msg(failed_match_message('tcsh', files))

        __echo_and_eval__(f"echo 'eval `register-python-argcomplete --shell tcsh mmpm`' >> {config}")

        print(complete_message(config))

    elif 'fish' in shell:
        files = ['.config/fish/config.fish']
        config = __match_shell_config__(files)

        if not config:
            mmpm.utils.fatal_msg(failed_match_message('fish', files))

        __echo_and_eval__(f"register-python-argcomplete --shell fish mmpm >> {config}")

        print(complete_message(config))

    else:
        mmpm.utils.fatal_msg(f'Unable install autocompletion for ({shell}). Please see {autocomplete_url} for help installing autocomplete')


def zip_mmpm_log_files() -> None:
    '''
    Compresses all log files in ~/.config/mmpm/log. The NGINX log files are
    excluded due to mostly irrelevant information the user, or I would need
    when creating GitHub issues

    Parameters:
        None

    Returns:
        None
    '''
    today = datetime.datetime.now()

    zip_file_name: str = f'mmpm-logs-{today.year}-{today.month}-{today.day}'
    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Compressing MMPM log files to {os.getcwd()}/{zip_file_name}.zip ')

    try:
        shutil.make_archive(zip_file_name, 'zip', mmpm.consts.MMPM_LOG_DIR)
    except Exception as error:
        print(mmpm.consts.RED_X)
        logger.error(str(error))
        mmpm.utils.error_msg('Failed to create zip archive of log files. See `mmpm log` for details (I know...the irony)')
        return

    print(mmpm.consts.GREEN_CHECK_MARK)


def guided_setup() -> None:
    '''
    Provides the user a guided configuration of the environment variables, and
    feature installation. This can be re-run as many times as necessary.

    Parameters:
        None

    Returns:
        None
    '''
    prompt_user: Callable = mmpm.utils.prompt_user
    valid_input: Callable = mmpm.utils.assert_valid_input

    print(mmpm.color.bright_green("Welcome to MMPM's guided setup!\n"))
    print("I'll help you setup your environment variables, and install additional features. Pressing CTRL-C will cancel the entire process.")
    print("There are 6 to 12 questions, depending on your answers. Let's get started.\n")

    magicmirror_root: str = ''
    magicmirror_uri: str = f'http://{gethostbyname(gethostname())}:8080'
    magicmirror_pm2_proc: str = ''
    magicmirror_docker_compose_file: str = ''
    mmpm_is_docker_image: bool = False
    install_gui: bool = False
    install_autocomplete: bool = False
    install_as_module: bool = False
    migrate_mmpm_db_keys: bool = False

    try:
        magicmirror_root = valid_input('What is the absolute path to the root of your MagicMirror installation (ie. /home/pi/MagicMirror)? ')
        mmpm_is_docker_image = prompt_user('Did you install MMPM as a Docker image, or using docker-compose?')

        if not mmpm_is_docker_image and prompt_user('Did you install MagicMirror using docker-compose?'):
            magicmirror_docker_compose_file = valid_input('What is the absolute path to the MagicMirror docker-compose file (ie. /home/pi/docker-compose.yml)? ')

        if not mmpm_is_docker_image and not magicmirror_docker_compose_file and prompt_user('Are you currently using PM2 with your MagicMirror?'):
            magicmirror_pm2_proc = valid_input('What is the name of the PM2 process for MagicMirror? ')

        if not prompt_user(f'Is {magicmirror_uri} the address used to open MagicMirror in your browser? '):
            magicmirror_uri = valid_input('What is the URL used to access MagicMirror (ie. http://192.168.0.3:8080)? ')

        migrate_mmpm_db_keys = prompt_user('Have you ever installed any version of MMPM < 2.01?')
        install_gui = not mmpm_is_docker_image and prompt_user('Would you like to install the MMPM GUI (web interface)?')
        install_as_module = prompt_user('Would you like to hide/show MagicMirror modules through MMPM?')
        install_autocomplete = prompt_user('Would you like to install tab-autocomplete for the MMPM CLI?')

    except KeyboardInterrupt:
        logger.info('User cancelled guided setup')
        print()
        sys.exit(0)

    with open(mmpm.consts.MMPM_ENV_FILE, 'w', encoding="utf-8") as env:
        json.dump({
            mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV: os.path.normpath(magicmirror_root),
            mmpm.consts.MMPM_MAGICMIRROR_URI_ENV: magicmirror_uri,
            mmpm.consts.MMPM_MAGICMIRROR_PM2_PROCESS_NAME_ENV: magicmirror_pm2_proc,
            mmpm.consts.MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE_ENV: os.path.normpath(magicmirror_docker_compose_file),
            mmpm.consts.MMPM_IS_DOCKER_IMAGE_ENV: mmpm_is_docker_image
        }, env, indent=2)

    if migrate_mmpm_db_keys:
        migrate()

    if install_as_module:
        install_mmpm_as_magicmirror_module(assume_yes=True)

    if install_gui:
        install_mmpm_gui(assume_yes=True)

    if install_autocomplete:
        install_autocompletion(assume_yes=True)

    print('\nBased on your responses, your environment variables have been set as:')
    display_mmpm_env_vars()

    print('\n\nDone!\n\nPlease review the above output for any additional suggested instructions.')

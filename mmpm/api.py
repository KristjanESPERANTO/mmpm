#!/usr/bin/env python3
import eventlet
eventlet.monkey_patch()

import os
import json
import shutil
from flask_cors import CORS
from flask import Flask, request, send_file, render_template, send_from_directory, Response
from mmpm import core, utils, consts
from mmpm.utils import log
from shelljob.proc import Group
from flask_socketio import SocketIO
from typing import Tuple, List, Dict


MMPM_EXECUTABLE: list = [os.path.join(os.path.expanduser('~'), '.local', 'bin', 'mmpm')]

app = Flask(
    __name__,
    root_path='/var/www/mmpm',
    static_folder="/var/www/mmpm/static",
)

app.config['CORS_HEADERS'] = 'Content-Type'

resources: dict = {
    r'/*': {'origins': '*'},
    r'/api/*': {'origins': '*'},
    r'/socket.io/*': {'origins': '*'},
}


CORS(app)
socketio = SocketIO(app, cors_allowed_origins='*')

GET: str = 'GET'
POST: str = 'POST'
DELETE: str = 'DELETE'

api = lambda path: f'/api/{path}'

def __modules__() -> dict:
    '''
    Returns dictionary of MagicMirror modules

    Parameters:
        None

    Returns:
        dict
    '''
    modules = core.load_modules()
    return modules


def __stream_cmd_output__(process: Group, cmd: list):
    '''
    Streams command output to socket.io client on frontend.

    Parameters:
        process (Group): the process object responsible for running the command
        cmd (List[str]): list of command arguments

    Returns:
        None
    '''
    command: list = MMPM_EXECUTABLE + cmd
    log.info(f"Executing {command}")
    process.run(command)

    try:
        while process.is_pending():
            log.info('Process pending')
            for _, line in process.readlines():
                socketio.emit('live-terminal-stream', {'data': str(line.decode('utf-8'))})
        log.info(f'Process complete: {command}')
    except Exception:
        pass


@socketio.on_error()
def error_handler(error) -> Tuple[str, int]:
    '''
    Socket.io error handler

    Parameters:
        error (str): error message

    Returns:
        tuple (str, int): error message and code
    '''
    message: str = f'An internal error occurred within flask_socketio: {error}'
    log.critical(message)
    return message, 500


@socketio.on('connect')
def on_connect() -> None:
    message: str = 'Server connected'
    log.info(message)
    socketio.emit('connected', {'data': message})


@socketio.on('disconnect')
def on_disconnect() -> None:
    message: str = 'Server disconnected'
    log.info(message)
    socketio.emit(message, {'data': message})

@app.after_request
def after_request(response: Response) -> Response:
    log.info('Headers being added after the request')
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers['Cache-Control'] = 'public, max-age=0'
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    return response


@app.route('/<path:path>', methods=[GET])
def static_proxy(path):
    return send_from_directory('./', path)


@app.route('/', methods=[GET, POST, DELETE])
def root() -> str:
    return render_template('index.html')


@app.errorhandler(500)
def server_error(error) -> Tuple[str, int]:
    return f'An internal error occurred [{__name__}.py]: {error}', 500


@app.route(api('all-modules'), methods=[GET])
def get_magicmirror_modules() -> dict:
    return __modules__()


@app.route(api('check-for-installation-conflicts'), methods=[POST])
def check_for_installation_conflicts() -> str:
    selected_modules: list = request.get_json(force=True)['selected-modules']
    log.info(f'User selected {selected_modules} to be installed')

    existing_module_dirs: List[str] = utils.get_existing_module_directories()
    result: Dict[str, list] = {'conflicts': []}

    for module in selected_modules:
        if module[consts.TITLE] in existing_module_dirs:
            conflicting_path: str = os.path.join(consts.MAGICMIRROR_MODULES_DIR, module[consts.TITLE])
            log.error(f'Conflict encountered. Found a package named {module[consts.TITLE]} already at {conflicting_path}')
            result['conflicts'].append(module)

    return json.dumps(result)

@app.route(api('install-modules'), methods=[POST])
def install_magicmirror_modules() -> str:
    selected_modules: list = request.get_json(force=True)['selected-modules']
    log.info(f'User selected {selected_modules} to be installed')

    modules_dir = os.path.join(consts.MAGICMIRROR_ROOT, 'modules')

    result: Dict[str, list] = {'failures': []}

    for module in selected_modules:
        success, error = utils.install_module(module, module[consts.TITLE], modules_dir, assume_yes=True)

        if not success:
            log.error(f'Failed to install {module[consts.TITLE]} with error of: {error}')
            module[consts.ERROR] = error
            result['failures'].append(module)
        else:
            log.info(f'Installed {module[consts.TITLE]}')

    return json.dumps(result)


@app.route(api('uninstall-modules'), methods=[POST])
def remove_magicmirror_modules() -> str:
    selected_modules: list = request.get_json(force=True)['selected-modules']
    log.info(f'User selected {selected_modules} to be removed')

    result: List[dict] = []

    for module in selected_modules:
        try:
            shutil.rmtree(module[consts.DIRECTORY])
            log.info(f'Removed {module[consts.DIRECTORY]}')
        except FileNotFoundError as error:
            log.error(f'Failed to remove {module[consts.DIRECTORY]}')
            module[consts.ERROR] = error
            result.append(module)

    return json.dumps(result)


@app.route(api('upgrade-modules'), methods=[POST])
def upgrade_magicmirror_modules() -> str:
    selected_modules: list = request.get_json(force=True)['selected-modules']
    log.info(f'Request to upgrade {selected_modules}')

    result: List[dict] = []

    for module in selected_modules:
        error = core.upgrade_module(module)
        if error:
            log.error(f'Failed to upgrade {module[consts.TITLE]} with error of: {error}')
            module[consts.ERROR] = error
            result.append(module)

    log.info('Finished executing upgrades')
    return json.dumps(result)


@app.route(api('all-installed-modules'), methods=[GET])
def get_installed_magicmirror_modules() -> dict:
    return core.get_installed_modules(__modules__())


@app.route(api('all-external-module-sources'), methods=[GET])
def get_external__modules__sources() -> dict:
    ext_sources: dict = {consts.EXTERNAL_MODULE_SOURCES: []}
    try:
        with open(consts.MMPM_EXTERNAL_SOURCES_FILE, 'r') as mmpm_ext_srcs:
            ext_sources[consts.EXTERNAL_MODULE_SOURCES] = json.load(mmpm_ext_srcs)[consts.EXTERNAL_MODULE_SOURCES]
    except IOError as error:
        log.error(error)
        pass
    return ext_sources


@app.route(api('add-external-module-source'), methods=[POST])
def add_external_module() -> str:
    external_source: dict = request.get_json(force=True)['external-source']

    result: List[dict] = []

    error: str = core.add_external_module(
        title=external_source.get('title'),
        author=external_source.get('author'),
        desc=external_source.get('description'),
        repo=external_source.get('repository')
    )

    return json.dumps({'error': "no_error" if not error else error})


@app.route(api('remove-external-module-source'), methods=[DELETE])
def remove_external_module_source() -> str:
    selected_modules: list = request.get_json(force=True)['external-sources']
    log.info(f'Request to remove external sources')

    ext_modules: dict = {}
    marked_for_removal: list = []

    try:
        with open(consts.MMPM_EXTERNAL_SOURCES_FILE, 'r') as mmpm_ext_srcs:
            ext_modules[consts.EXTERNAL_MODULE_SOURCES] = json.load(mmpm_ext_srcs)[consts.EXTERNAL_MODULE_SOURCES]
        log.info(f'Read external modules from {consts.MMPM_EXTERNAL_SOURCES_FILE}')
    except IOError as error:
        log.error(error)
        return json.dumps({'error': error})

    for selected_module in selected_modules:
        # will clean this ugliness up, but for the moment leaving just because it works
        del selected_module[consts.DIRECTORY]
        del selected_module[consts.CATEGORY]

        for module in ext_modules[consts.EXTERNAL_MODULE_SOURCES]:
            print(module)
            if module == selected_module:
                marked_for_removal.append(module)
                log.info(f'Found matching external module ({module[consts.TITLE]}) and marked for removal')

    for module in marked_for_removal:
        ext_modules[consts.EXTERNAL_MODULE_SOURCES].remove(module)
        log.info(f'Removed {module[consts.TITLE]}')

    try:
        with open(consts.MMPM_EXTERNAL_SOURCES_FILE, 'w') as mmpm_ext_srcs:
            json.dump(ext_modules, mmpm_ext_srcs)
        log.info(f'Wrote updated external modules to {consts.MMPM_EXTERNAL_SOURCES_FILE}')
    except IOError as error:
        log.error(error)
        return json.dumps({'error': error})

    log.info(f'Wrote external modules to {consts.MMPM_EXTERNAL_SOURCES_FILE}')
    return json.dumps({'error': "no_error"})


@app.route(api('refresh-modules'), methods=[GET])
def force_refresh_magicmirror_modules() -> str:
    log.info(f'Recieved request to refresh modules')
    process: Group = Group()
    Response(__stream_cmd_output__(process, ['-f', '--GUI']), mimetype='text/plain')
    log.info('Finished refresh')
    return json.dumps(True)


@app.route(api('get-magicmirror-config'), methods=[GET])
def get_magicmirror_config():
    path: str = consts.MAGICMIRROR_CONFIG_FILE
    result: str = send_file(path, attachment_filename='config.js') if path else ''
    log.info('Retrieving MagicMirror config')
    return result


@app.route(api('update-magicmirror-config'), methods=[POST])
def update_magicmirror_config() -> str:
    data: dict = request.get_json(force=True)
    log.info('Saving MagicMirror config file')

    try:
        with open(consts.MAGICMIRROR_CONFIG_FILE, 'w') as config:
            config.write(data.get('code'))
    except IOError:
        return json.dumps(False)
    return json.dumps(True)


@app.route(api('start-magicmirror'), methods=[GET])
def start_magicmirror() -> str:
    '''
    Restart the MagicMirror by killing all Chromium processes, the
    re-running the startup script for MagicMirror

    Parameters:
        None

    Returns:
        bool: True if the command was called, False it appears that MagicMirror is currently running
    '''
    # there really isn't an easy way to capture return codes for the background process, so, for the first version, let's just be lazy for now
    # need to find way to capturing return codes

    # if these processes are all running, we assume MagicMirror is running currently
    if utils.get_pids('chromium') and utils.get_pids('node') and utils.get_pids('npm'):
        log.info('MagicMirror appears to be running already. Returning False.')
        return json.dumps(False)

    log.info('MagicMirror does not appear to be running currently. Returning True.')
    core.start_magicmirror()
    return json.dumps(True)


@app.route(api('restart-magicmirror'), methods=[GET])
def restart_magicmirror() -> str:
    '''
    Restart the MagicMirror by killing all Chromium processes, the
    re-running the startup script for MagicMirror

    Parameters:
        None

    Returns:
        bool: Always True only as a signal the process was called
    '''
    # same issue as the start-magicmirror api call
    core.restart_magicmirror()
    return json.dumps(True)


@app.route(api('stop-magicmirror'), methods=[GET])
def stop_magicmirror() -> str:
    '''
    Stop the MagicMirror by killing all Chromium processes

    Parameters:
        None

    Returns:
        bool: Always True only as a signal the process was called
    '''
    # same sort of issue as the start-magicmirror call
    core.stop_magicmirror()
    return json.dumps(True)


@app.route(api('restart-raspberrypi'), methods=[GET])
def restart_raspberrypi() -> str:
    '''
    Reboot the RaspberryPi

    Parameters:
        None

    Returns:
        success (bool): If the command fails, False is returned. If success, the return will never reach the interface
    '''

    log.info('Restarting RaspberryPi')
    core.stop_magicmirror()
    error_code, _, _ = utils.run_cmd(['sudo', 'reboot'])
    # if success, it'll never get the response, but we'll know if it fails
    return json.dumps(bool(not error_code))


@app.route(api('shutdown-raspberrypi'), methods=[GET])
def turn_off_raspberrypi() -> str:
    '''
    Shut down the RaspberryPi

    Parameters:
        None

    Returns:
        success (bool): If the command fails, False is returned. If success, the return will never reach the interface
    '''

    log.info('Shutting down RaspberryPi')
    # if success, we'll never get the response, but we'll know if it fails
    core.stop_magicmirror()
    error_code, _, _ = utils.run_cmd(['sudo', 'shutdown', '-P', 'now'])
    return json.dumps(bool(not error_code))


@app.route(api('upgrade-magicmirror'), methods=[GET])
def upgrade_magicmirror() -> str:
    log.info(f'Request to upgrade MagicMirror')
    process: Group = Group()
    Response(__stream_cmd_output__(process, ['-M', '--GUI']), mimetype='text/plain')
    log.info('Finished installing')

    if utils.get_pids('node') and utils.get_pids('npm') and utils.get_pids('electron'):
        core.restart_magicmirror()

    return json.dumps(True)

#@app.route(api('download-log-files'), methods=[GET])
#def download_log_files():
#    path: str = consts.MAGICMIRROR_CONFIG_FILE
#    result: str = send_file(path, attachment_filename='config.js') if path else ''
#    log.info('Retrieving MMPM log files')
#    return result

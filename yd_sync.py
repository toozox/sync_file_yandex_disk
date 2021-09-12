import requests
from time import sleep
import configparser
import os
import pyminizip
from zipfile import ZipFile
from datetime import datetime, timedelta

import webdav.client

import client_data

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

config_file = 'config.ini'
passwd_file = 'passwd'
zpasswd_file = 'zpasswd'
zfile = 'compressed.zip'
mod_time_file = 'modtime'


def gen_default_device_info():
    from socket import gethostname
    from platform import system
    from uuid import uuid4
    res = dict()
    res['device_name'] = f"{system()}.{gethostname()}"
    res['device_id'] = str(uuid4())
    return res


def get_device_info():
    default_dev_info = gen_default_device_info()
    config = configparser.ConfigParser()
    if os.path.isfile(config_file):
        config.read(config_file)
    # если какого либо значения нет в конфиге то он генерируется
    # и записывается в конфигурационный файл
    if 'device' not in config.sections():
        config['device'] = dict()
    for key in default_dev_info:
        if key not in config['device'].keys():
            config['device'][key] = default_dev_info[key]
    # запись данных
    with open(config_file, 'w') as configfile:
        config.write(configfile)
    return config['device']


def get_token():
    dev_info = get_device_info()
    url = "https://oauth.yandex.ru/device/code"
    data = {"client_id": client_data.client_id,
            "device_id": dev_info["device_id"],
            "device_name": dev_info["device_name"]}
    res = requests.post(url, data=data)
    if res.headers['Content-Type'] != 'application/json':
        return None
    res_json = res.json()
    user_code = res_json['user_code']
    device_code = res_json['device_code']
    verify_url = res_json['verification_url']
    interval = res_json['interval']
    time_to_wait = res_json['expires_in']
    print(f'Введите следующий код на странице {verify_url}: {user_code}')
    url = "https://oauth.yandex.ru/token"
    data.update({"client_secret": client_data.client_secret,
                 "code": device_code,
                 "grant_type": "device_code",
                 })
    counter = 0
    res_json = None
    while(counter < time_to_wait):
        counter += interval
        sleep(interval)
        res = requests.post(url, data=data)
        if res.status_code == 200:
            print('Токен получен')
            res_json = res.json()
            break
        else:
            print(f'{res.status_code} Код ещё не подтверждён')
    return res_json


def save_token(token):
    config = configparser.ConfigParser()
    config['tokens'] = {'access_token': token['access_token'],
                        'refresh_token': token['refresh_token']
                        }
    with open(passwd_file, 'w') as configfile:
        config.write(configfile)


def sync_file(yd_client):
    config = configparser.ConfigParser()
    config.read(config_file)
    remote_path = config['file']['remote_path']
    local_path = config['file']['local_path']
    remote_modified = yd_client.info(remote_path)['modified']
    remote_modified = datetime.strptime(remote_modified, "%a, %d %b %Y %H:%M:%S %Z")
    local_zf_modified = datetime.utcfromtimestamp(int(os.path.getmtime(zfile)))
    with open(mod_time_file, 'r') as f:
        saved_f_modified = int(float(f.read()))
    f_modified = int(os.path.getmtime(local_path))
    # если разница между удалённым архивом и локальным архивом больше
    # одной минуты, то на сервере более свежая версия
    if (remote_modified - local_zf_modified) > timedelta(minutes=1):
        # если локальный файл тоже изменился (конфликт)
        if f_modified > saved_f_modified:
            print('Удалённая копия и локальная копия изменены,\n'
                  'поэтому возник конфлик слияния.\n'
                  'Как решить этот конфликт?\n'
                  '1 Загрузить локальную копию в облако.\n'
                  '2 Скачать удалённую копию для ручного слияния.\n'
                  '3 Завершить работу программы\n')
            in_var = int(input('> '))
            if in_var == 3:
                exit()
            elif in_var == 1:
                send_file(yd_client)
            elif in_var == 2:
                save_path = input('Введите путь, куда сохранить файл: ')
                # скачать по пути, куда указал пользователь
                get_file_tmp(yd_client, save_path)
            return
        # если локальная копия не изменилась
        else:
            # скачиваем версию из облака
            get_file(yd_client)
            return
    # если локальная копия файла изменилась, а не сервера старая версия
    elif f_modified > saved_f_modified:
        # загружаем локальную копию на сервер
        send_file(yd_client)
        return

    print("Нечего синхронизировать")


def all_files_exists(yd_client):
    if not os.path.isfile(zpasswd_file):
        print('Нет файла с паролем для шифрования/расшифровки архива')
        return False

    config = configparser.ConfigParser()
    config.read(config_file)

    if not 'file' in config.sections():
        print(f"В конфиге {config_file} нет секции [file]")
        return False

    if not config['file'].get('local_path'):
        print(f"В конфиге {config_file} нет параметра local_path")
        return False

    if not config['file'].get('remote_path'):
        print(f"В конфиге {config_file} нет параметра remote_path")
        return False

    local_path = config['file']['local_path']
    local_file = True
    if not os.path.isfile(local_path):
        local_file = False

    remote_path = config['file']['remote_path']
    remote_zfile = True
    if not yd_client.check(remote_path):
        remote_zfile = False

    if not local_file and not remote_zfile:
        print("На локальном компьютере и в облаке отсутствуют файлы для синхронизации,\n"
              f"либо они неверно указаны в {config_file}")
        return False

    if not remote_zfile:
        # заархивировать файл и отправить в облако
        send_file(yd_client)
        return

    if not local_file:
        # получить файл из облака
        get_file(yd_client)
        return

    return True


# архивация файла и отправка в облако
def send_file(yd_client):
    config = configparser.ConfigParser()
    config.read(config_file)
    local_file = config['file']['local_path']
    remote_path = config['file']['remote_path']
    with open(zpasswd_file) as f:
        zpassword = f.read()
    pyminizip.compress(local_file, None, zfile, zpassword, 3)
    print(f"Отправка запароленного архива в облако")
    yd_client.upload_sync(remote_path, zfile)
    # сохраняем время модификации файла, который отправлен в облаков
    with open(mod_time_file, 'w') as f:
        f.write(str(os.path.getmtime(local_file)))
    print(f"Архив успешно отправлен в облако")


def get_file_tmp(yd_client, save_path):
    config = configparser.ConfigParser()
    config.read(config_file)
    local_file = save_path
    remote_file = config['file']['remote_path']
    with open('zpasswd', 'r') as f:
        zpassword = f.read()

    print("Получение файла из облака")
    zfile = os.path.join(save_path, 'tmp.zip')
    os.makedirs(save_path)
    yd_client.download_file(remote_file, zfile)
    with ZipFile(zfile) as z:
        z.extractall(path=save_path, pwd=bytes(zpassword, 'utf-8'))
    os.remove(zfile)
    print("Файл успешно получен")


def get_file(yd_client):
    config = configparser.ConfigParser()
    config.read(config_file)
    local_file = config['file']['local_path']
    remote_file = config['file']['remote_path']
    with open('zpasswd', 'r') as f:
        zpassword = f.read()

    # делаем бэкап сущ. файла, если он есть
    # TODO сделать функционал бэкапа
    if os.path.isfile(local_file):
        pass

    print("Получение файла из облака")
    yd_client.download_sync(remote_file, zfile)
    file_dir = os.path.dirname(local_file)
    with ZipFile(zfile) as z:
        z.extractall(path=file_dir, pwd=bytes(zpassword, 'utf-8'))

    # сохраняем время модификации файла
    with open(mod_time_file, 'w') as f:
        f.write(str(os.path.getmtime(local_file)))

    print("Файл успешно получен")


def main():
    if not os.path.isfile(passwd_file):
        tokens = get_token()
        if not tokens:
            print("Не удалось получить токен")
            return
        else:
            save_token(tokens)
    else:
        saved_tokens = configparser.ConfigParser()
        saved_tokens.read(passwd_file)
        tokens = dict(saved_tokens['tokens'])

    options = {
        'webdav_hostname': "https://webdav.yandex.ru",
        'webdav_token': tokens['access_token']
    }
    yd_client = webdav.client.Client(options)
    if not yd_client.check():
        print('Ошибка авторизации')
        return
    else:
        print('Успешная авторизация')

    # проверка, есть ли все необходимые файлы
    # и в облаке и на локальном компьютере
    if all_files_exists(yd_client):
        sync_file(yd_client)


if __name__ == "__main__":
    main()

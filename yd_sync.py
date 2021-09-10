import requests
from time import sleep
import configparser
import os
import client_data

config_file = 'config.ini'
passwd_file = 'passwd'


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


def main():
    if not os.path.isfile(passwd_file):
        tokens = get_token()
        if not tokens:
            print("Не удалось получить токен")
            return
        else:
            save_token(tokens)
    else:
        config = configparser.ConfigParser()
        config.read(passwd_file)
        tokens = dict(config['tokens'])


if __name__ == "__main__":
    main()

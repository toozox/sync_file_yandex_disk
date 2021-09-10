import requests
from time import sleep
import configparser
import client_data


def get_token():
    url = "https://oauth.yandex.ru/device/code"
    data = {"client_id": client_data.client_id, }
    res = requests.post(url, data=data)
    if res.headers['Content-Type'] != 'application/json':
        return False
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
    with open('passwd', 'w') as configfile:
        config.write(configfile)


def main():
    token = get_token()
    if not token:
        print("Не удалось получить токен")
        return
    else:
        save_token(token)


if __name__ == "__main__":
    main()

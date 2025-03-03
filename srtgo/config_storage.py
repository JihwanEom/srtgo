"""
SRTgo 설정 저장 모듈 (keyring 대체용)
"""
import json
import os
from pathlib import Path

# 설정 파일 경로
CONFIG_DIR = Path.home() / '.srtgo'
CONFIG_FILE = CONFIG_DIR / 'config.json'

def ensure_config_dir():
    """설정 디렉토리가 존재하는지 확인하고 없으면 생성"""
    if not CONFIG_DIR.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def load_config():
    """설정 파일 로드"""
    ensure_config_dir()
    
    if not CONFIG_FILE.exists():
        return {}
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print("설정 파일이 손상되었습니다. 새로운 설정 파일을 생성합니다.")
        return {}

def save_config(config):
    """설정 파일 저장"""
    ensure_config_dir()
    
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def get_password(service, key):
    """keyring.get_password 대체 함수"""
    config = load_config()
    service_config = config.get(service, {})
    return service_config.get(key)

def set_password(service, key, value):
    """keyring.set_password 대체 함수"""
    config = load_config()
    
    if service not in config:
        config[service] = {}
    
    config[service][key] = value
    save_config(config)

def delete_password(service, key):
    """keyring.delete_password 대체 함수"""
    config = load_config()
    
    if service in config and key in config[service]:
        del config[service][key]
        save_config(config)

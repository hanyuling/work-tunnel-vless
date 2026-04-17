# -*-coding:utf-8 -*-
import requests
import json
import time
import os

# 配置常量
CONFIG_FILE = "deploy_history.json"
API_URL = "https://api.containers.back4app.com"
EXPIRATION_WINDOW = 3300  # 55分钟 (55 * 60)，留5分钟缓冲

HEADERS = {
    "Content-type": "application/json",
    "Cookie": os.environ["BACK4APP_COOKIE"]
}

# 应用映射
APP_ID_MAP = {
    "62f7d2d2-e262-48c2-843b-c7bca9dd5278": "30c4ae4d-5e17-4bdb-a37d-73a2a8489775"
}

def load_history():
    """从本地文件加载部署历史"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_history(history):
    """保存部署历史到本地"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(history, f)

def list_apps():
    query = {
        "query": "query Apps { apps { id name mainService { repository { fullName } mainServiceEnvironment { mainCustomDomain { status } } } } }"
    }
    try:
        res = requests.post(API_URL, json=query, headers=HEADERS, timeout=10)
        res.raise_for_status()
        apps = res.json().get("data", {}).get("apps", [])
        
        status_list = []
        for app in apps:
            status_list.append({
                "app_id": app["id"],
                "app_name": app["mainService"]['repository']['fullName'],
                "domain_status": app["mainService"]["mainServiceEnvironment"]["mainCustomDomain"]["status"]
            })
        return status_list
    except Exception as e:
        print(f"获取应用列表失败: {e}")
        return []

def trigger_deploy(app_id):
    service_env_id = APP_ID_MAP.get(app_id)
    if not service_env_id:
        return False

    payload = {
        "operationName": "triggerManualDeployment",
        "variables": {"serviceEnvironmentId": service_env_id},
        "query": "mutation triggerManualDeployment($serviceEnvironmentId: String!) { triggerManualDeployment(serviceEnvironmentId: $serviceEnvironmentId) { id status } }"
    }
    
    try:
        res = requests.post(API_URL, json=payload, headers=HEADERS, timeout=10)
        if res.status_code == 200 and "error" not in res.text:
            return True
    except Exception as e:
        print(f"触发部署异常: {e}")
    return False

def auto_redeploy():
    history = load_history()
    current_time = time.time()
    apps = list_apps()
    
    for app in apps:
        app_id = app["app_id"]
        app_name = app["app_name"]
        last_deploy = history.get(app_id, 0)
        
        # 逻辑判断：
        # 1. 距离上次部署是否不满 55 分钟？如果是，直接跳过，不调 API 检查具体状态
        if current_time - last_deploy < EXPIRATION_WINDOW:
            minutes_left = int((EXPIRATION_WINDOW - (current_time - last_deploy)) / 60)
            print(f"-> {app_name}: 部署尚在有效期内，约 {minutes_left} 分钟后重新评估")
            continue

        # 2. 如果超过 55 分钟，检查 API 状态
        if app["domain_status"] == "EXPIRED":
            if app_id not in APP_ID_MAP:
                print(f"! {app_name}: 缺少 serviceEnvId 映射")
                continue
            
            print(f"* {app_name}: 域名已过期，执行重新部署...")
            if trigger_deploy(app_id):
                history[app_id] = time.time()
                print(f"√ {app_name}: 部署指令发送成功")
            else:
                print(f"× {app_name}: 部署失败")
        else:
            # 域名虽然过了55分钟但还没显示 EXPIRED，更新一下时间，避免频繁请求
            print(f"-> {app_name}: 状态正常 ({app['domain_status']})")
            
    save_history(history)

if __name__ == '__main__':
    auto_redeploy()

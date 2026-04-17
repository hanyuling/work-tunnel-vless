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
    "Cookie": "connect.sid=s%3Aayt1ZhdLKtSrHM79eQ1UcY-6DmbsZcS8.U99ce2oQ9CvkwWXRVVeNLPFtB6XvBWDxWp0CU5LPiGk; _gcl_au=1.1.1027654487.1776431875; landingPage=%7B%22origin%22%3A%22https%3A%2F%2Fwww.back4app.com%22%2C%22host%22%3A%22www.back4app.com%22%2C%22pathname%22%3A%22%2Flogin%22%7D; _ga=GA1.1.1763371118.1776431876; ab-XjkrUHOQKm=DZPgaVjide!1; b4a_amplitude_device_id=BXh9MSWWCZemQeULsk2MDW; __zlcmid=1X6oRVUYKdZtyKK; amp_bf3379=hQ9Bu8N0TZ801PLoId_djn...1jmdsmb1e.1jmdsmb1f.0.2.2; amp_bf3379_back4app.com=BXh9MSWWCZemQeULsk2MDW...1jmdpenrl.1jmdt0inc.s.2.u; AMP_bf3379918c=JTdCJTIyZGV2aWNlSWQlMjIlM0ElMjJCWGg5TVNXV0NaZW1RZVVMc2syTURXJTIyJTJDJTIydXNlcklkJTIyJTNBJTIyaGFueXVsaW5nd3JnJTQwMTYzLmNvbSUyMiUyQyUyMnNlc3Npb25JZCUyMiUzQTE3NzY0MzE4ODIxMDElMkMlMjJvcHRPdXQlMjIlM0FmYWxzZSUyQyUyMmxhc3RFdmVudFRpbWUlMjIlM0ExNzc2NDM1NjEyMzk4JTdE; __gtm_referrer=https%3A%2F%2Fcontainers.back4app.com%2F; _rdt_uuid=1776431876390.8a3e2401-fa4a-419d-aba6-ced4f1272e47; _rdt_em=:f0944b6c79674d0478dff88a835bcf0079243d35f5faf91adf2bba1db1b06cf7,0f1f9d9d80e0e0137467151dea38eba8ca72f64fa6d370fdce72982c858384cb,9e8f5221595f55bd9e8a4c64ce88708bece4362cdd72011fefea5cbe2a786d27; _rdt_pn=:125~7e071fd9b023ed8f18458a73613a0834f6220bd5cc50357ba3493c6040a9ea8c; _ga_FJK5KX97E0=GS2.1.s1776431875$o1$g1$t1776436161$j22$l0$h1460255979"
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

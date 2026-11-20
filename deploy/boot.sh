#!/bin/bash
# 在 NapCat 官方容器里做三件事，然后照常启动：
#   1) 打开 OneBot HTTP 接口（容器内 3000）
#   2) 放好每日点赞脚本并挂到后台
#   3) 交给官方 entrypoint 启动 QQ
set -u

SRC="${SRC:-https://raw.githubusercontent.com/zhaofan128/qq-cloud-liker/main/deploy}"
cd /app || exit 1

mkdir -p /app/napcat/config

if [ ! -f /app/napcat/config/onebot11.json ]; then
    if [ -n "${LOCAL_SRC:-}" ]; then
        cp "${LOCAL_SRC}/onebot11.json" /app/napcat/config/onebot11.json
    else
        curl -fsSL "${SRC}/onebot11.json" -o /app/napcat/config/onebot11.json
    fi
fi

if [ ! -f /app/dailylike.py ]; then
    if [ -n "${LOCAL_SRC:-}" ]; then
        cp "${LOCAL_SRC}/dailylike.py" /app/dailylike.py
    else
        for i in 1 2 3; do
            curl -fsSL "${SRC}/dailylike.py" -o /app/dailylike.py && break
            sleep 3
        done
    fi
fi

if ! pgrep -f "python3 /app/dailylike.py" > /dev/null 2>&1; then
    nohup python3 /app/dailylike.py >> /app/like.log 2>&1 &
fi

exec bash /app/entrypoint.sh

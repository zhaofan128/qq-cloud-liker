#!/bin/bash
# 同时启动两件事：
#   1) dailylike.py 常驻，每天到点给好友点名片赞
#   2) NapCat 本体（登录 QQ、提供 OneBot 接口）
python3 /app/dailylike.py >> /app/like.log 2>&1 &

cd /app || exit 1
exec bash entrypoint.sh

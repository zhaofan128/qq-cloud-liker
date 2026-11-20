#!/bin/bash
# 在已经跑起来的 NapCat 容器里就地安装（ClawCloud 的 Terminal 里执行）
# 用法：curl -fsSL <raw>/deploy/setup.sh | bash
set -u
SRC="${SRC:-https://raw.githubusercontent.com/zhaofan128/qq-cloud-liker/main/deploy}"

mkdir -p /app/napcat/config

need_restart=0
if [ ! -f /app/napcat/config/onebot11.json ]; then
    if curl -fsSL "$SRC/onebot11.json" -o /app/napcat/config/onebot11.json; then
        need_restart=1
    fi
fi

curl -fsSL "$SRC/dailylike.py" -o /app/dailylike.py

pkill -f "python3 /app/dailylike.py" 2>/dev/null
sleep 1
nohup python3 /app/dailylike.py >> /app/like.log 2>&1 &
sleep 1

echo ""
if [ "$need_restart" = "1" ]; then
    echo "① 接口配置已写入。请回应用详情点 Restart。"
    echo "② 重启完再执行一次这条命令，点赞就生效了："
    echo "   curl -fsSL ${SRC}/setup.sh | bash"
else
    echo "daily liker started"
    echo "每天 ${LIKE_AT:-10:00} 给全部好友点 ${LIKE_TIMES:-10} 个名片赞"
    echo "立刻试一次：python3 /app/dailylike.py --once"
    echo "看日志：tail -f /app/like.log"
fi

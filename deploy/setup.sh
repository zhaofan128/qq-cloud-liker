#!/bin/bash
# 在已经跑起来的 NapCat 容器里就地安装（ClawCloud 的 Terminal 里执行）
# 用法：curl -fsSL <raw>/deploy/setup.sh | bash
set -u
SRC="${SRC:-https://raw.githubusercontent.com/zhaofan128/qq-cloud-liker/main/deploy}"

mkdir -p /app/napcat/config

if [ ! -f /app/napcat/config/onebot11.json ]; then
    curl -fsSL "$SRC/onebot11.json" -o /app/napcat/config/onebot11.json
    echo "已写入 OneBot 配置（需要重启一次容器才生效）"
fi

curl -fsSL "$SRC/dailylike.py" -o /app/dailylike.py

pkill -f "python3 /app/dailylike.py" 2>/dev/null
sleep 1
nohup python3 /app/dailylike.py >> /app/like.log 2>&1 &

echo ""
echo "daily liker started"
echo "- 每天 ${LIKE_AT:-10:00} 自动给全部好友点 ${LIKE_TIMES:-10} 个名片赞"
echo "- 立刻试一次：python3 /app/dailylike.py --once"
echo "- 看日志：tail -f /app/like.log"

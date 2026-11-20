# 云端名片赞：NapCat + 每日自动 send_like
# 部署到任意支持 Docker 的云平台（ClawCloud / Zeabur / Koyeb / 自建服务器）
FROM mlikiowa/napcat-docker:latest

ENV TZ=Asia/Shanghai \
    LIKE_AT=10:00 \
    LIKE_TIMES=10 \
    LIKE_GAP=1.2 \
    ONEBOT_API=http://127.0.0.1:3000

# 预先写好 OneBot HTTP 服务端配置，省去在 WebUI 里手点
COPY onebot11.json /app/napcat/config/onebot11.json

COPY dailylike.py /app/dailylike.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENTRYPOINT ["/bin/bash", "/app/start.sh"]

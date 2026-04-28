FROM python:3.11-slim

WORKDIR /bot

COPY discord-bot/requirements.txt /tmp/requirements.txt
RUN pip install --quiet --no-cache-dir -r /tmp/requirements.txt

COPY discord-bot/ /bot/

CMD ["python3", "-u", "/bot/bot.py"]

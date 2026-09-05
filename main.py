import os
import sqlite3
import json
import random
import re
import discord
from discord.ext import commands
from discord.ui import View, Button
import google.generativeai as genai

# ----------------------------------------------------
# 1. API 키 및 봇 설정
# ----------------------------------------------------
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="", intents=intents)

# ----------------------------------------------------
# 2. SQLite 데이터베이스 연동
# ----------------------------------------------------
def init_db():
    conn = sqlite3.connect("game.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS players (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            start_year INT,
            curr_year INT,
            curr_month INT,
            curr_day INT,
            age INT,
            identity TEXT,
            lead INT,
            war INT,
            intel INT,
            pol INT,
            cha INT,
            hp INT,
            max_hp INT,
            troops INT,
            gold INT,
            rations INT,
            weapons TEXT,
            location TEXT,
            renown INT,
            notoriety INT,
            situation TEXT,
            relationships TEXT,
            canon_history TEXT,
            if_history TEXT,
            creation_step INT,
            is_dead INT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_player(user_id):
    conn = sqlite3.connect("game.db")
    c = conn.cursor()
    c.execute("SELECT * FROM players WHERE user_id = ?", (str(user_id),))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    cols = [
        "user_id", "name", "start_year", "curr_year", "curr_month", "curr_day",
        "age", "identity", "lead", "war", "intel", "pol", "cha",
        "hp", "max_hp", "troops", "gold", "rations", "weapons",
        "location", "renown", "notoriety", "situation", "relationships",
        "canon_history", "if_history", "creation_step", "is_dead"
    ]
    return dict(zip(cols, row))

def save_player(p):
    conn = sqlite3.connect("game.db")
    c = conn.cursor()
    cols = list(p.keys())
    placeholders = ", ".join(["?"] * len(cols))
    updates = ", ".join([f"{col} = ?" for col in cols])
    sql = f'''
        INSERT INTO players ({", ".join(cols)})
        VALUES ({placeholders})
        ON CONFLICT(user_id) DO UPDATE SET {updates}
    '''
    c.execute(sql, list(p.values()) + list(p.values()))
    conn.commit()
    conn.close()

# ----------------------------------------------------
# 3. Gemini GM AI 두뇌 엔진
# ----------------------------------------------------
SYSTEM_PROMPT = """
당신은 삼국지연의 세계관을 엄격하게 관리하는 정통 TRPG Game Master(GM)입니다.
플레이어의 행동을 평가하고 판정하며, 삼국지의 생생한 서사와 코에이 최신작 기반 인물 성격을 묘사합니다.

[핵심 룰 & 행동 처리 지침]
1. GM은 플레이어의 행동 입력에 대해서만 중립적으로 서술하며 불필요한 사견을 붙이지 않습니다.
2. 플레이어의 실제 의도와 물리적 현실을 엄밀히 반영합니다. 
   - 스스로 목숨을 끊으려 하거나 터무니없는 행동을 할 경우, 전술적 이득 같은 엉뚱한 결과를 내지 말고 부상, 사망, 패널티로 즉각 처리하십시오.
3. 역사 구분 표기:
   - 본래의 정사/연의 역사적 사실이나 배경은 반드시 `[정사/연의 고증]` 말머리를 달아 서술합니다.
   - 플레이어의 행동으로 바뀐 분기나 나비효과는 반드시 `[변형된 역사 - IF]` 말머리를 달아 서술합니다.
4. 주사위 50 판정 (1d50):
   - 기본 구간: 대성공(1~3), 성공(4~25), 실패(26~46), 대실패(47~50).
   - 행동 난이도, 상대 장수와의 스탯 차이, 지형/신뢰도 유불리에 따라 구간이 실시간 변동됩니다.
5. 시간 및 군량:
   - 행동마다 현실적인 이동 시간 및 작전 시간(일수)을 소모합니다.
   - 식량(1인/1군 섭취량)과 소지 무기를 감안해 서술합니다.
6. 사망 처리:
   - HP가 0이 되거나 대실패로 인한 치명상으로 사망할 경우 즉시 게임 오버로 판정하고, 평생의 일대기 요약, 사후 2000년의 대체역사 나비효과, 후대 학자들의 평가를 길고 장엄하게 서술하십시오.

[출력 형식 - 반드시 아래 유효한 JSON 포맷만 반환]
```json
{
  "dice_roll": 18,
  "thresholds": "대성공(1~5) / 성공(6~28) / 실패(29~45) / 대실패(46~50)",
  "result_grade": "성공",
  "narrative": "스토리 내용 및 대사 (고증/IF 말머리 포함)",
  "days_passed": 3,
  "stat_changes": {
    "hp": 0,
    "troops": 0,
    "gold": 0,
    "rations": -2,
    "lead": 0,
    "war": 0,
    "intel": 1,
    "pol": 0,
    "cha": 0,
    "renown": 1,
    "notoriety": 0
  },
  "location": "현재 위치(변동 없으면 기존 유지)",
  "situation": "처한 상황 1~2줄 요약",
  "met_npc": {
    "name": "인물 이름 (새로 만났거나 호감도 변동된 인물, 없으면 null)",
    "trust_delta": 5,
    "favor_delta": 5
  },
  "canon_event": "원래 연의에서 이 시기/장소에 일어난 사건",
  "if_event": "플레이어로 인해 분기된 대체역사 흐름",
  "is_game_over": false,
  "game_over_narrative": ""
}

import os
import sqlite3
import json
import random
import re
import asyncio
from aiohttp import web, ClientSession
import discord
from discord.ext import commands
from discord.ui import View, Button

# 1. 환경 변수 및 디스코드 설정
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="", intents=intents)

# 2. SQLite DB 설정
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

# 3. Gemini REST API 엔진
SYSTEM_PROMPT = """당신은 삼국지 정통 TRPG GM입니다.
규칙:
1. 플레이어 행동에 따른 전개 결과를 200~400자 내외로 박진감 있게 서술하세요.
2. 1d50 주사위 판정: 1~3(대성공), 4~25(성공), 26~46(실패), 47~50(대실패).
3. 반드시 아래 순수 JSON 포맷 하나만 반환하세요:
{
  "dice_roll": 15,
  "thresholds": "대성공(1~3)/성공(4~25)/실패(26~46)/대실패(47~50)",
  "result_grade": "성공",
  "narrative": "스토리 서술",
  "days_passed": 1,
  "stat_changes": {"hp": 0, "troops": 0, "gold": 0, "rations": -1, "lead": 0, "war": 0, "intel": 0, "pol": 0, "cha": 0, "renown": 1, "notoriety": 0},
  "location": "현재 위치",
  "situation": "상황 요약 한 줄",
  "met_npc": null,
  "canon_event": "원전 사건",
  "if_event": "대체역사 전개",
  "is_game_over": false,
  "game_over_narrative": ""
}"""

async def query_gemini_gm(player, action_text):
    if not GEMINI_API_KEY:
        return {
            "dice_roll": random.randint(1, 50),
            "result_grade": "오류",
            "narrative": "GEMINI_API_KEY 환경변수가 설정되지 않았습니다.",
            "days_passed": 0,
            "stat_changes": {},
            "location": player['location'],
            "situation": player['situation']
        }

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"[플레이어 상태]\n"
        f"이름: {player['name']} ({player['identity']}, {player['age']}세)\n"
        f"현재: 서기 {player['curr_year']}년 {player['curr_month']}월 {player['curr_day']}일\n"
        f"무력 {player['war']} / 지력 {player['intel']} / 통솔 {player['lead']} / 정치 {player['pol']} / 매력 {player['cha']}\n"
        f"병력 {player['troops']}명 / 금 {player['gold']}냥 / 군량 {player['rations']}포대 / 무기 {player['weapons']}\n"
        f"위치: {player['location']}\n"
        f"[플레이어 행동]\n{action_text}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }

    endpoints = [
        ("v1beta", "gemini-3.6-flash"),
        ("v1", "gemini-3.6-flash"),
        ("v1beta", "gemini-2.5-flash"),
        ("v1beta", "gemini-1.5-flash-latest")
    ]

    last_error = ""
    async with ClientSession() as session:
        for ver, model in endpoints:
            url = f"https://generativelanguage.googleapis.com/{ver}/models/{model}:generateContent?key={GEMINI_API_KEY}"
            try:
                async with session.post(url, json=payload, timeout=25) as resp:
                    resp_text = await resp.text()
                    if resp.status == 200:
                        data = json.loads(resp_text)
                        raw = data['candidates'][0]['content']['parts'][0]['text']
                        match = re.search(r"\{.*\}", raw, re.DOTALL)
                        if match:
                            return json.loads(match.group(0))
                        return {
                            "dice_roll": random.randint(1, 50),
                            "result_grade": "진행",
                            "narrative": raw[:800],
                            "days_passed": 1,
                            "stat_changes": {},
                            "location": player['location'],
                            "situation": player['situation']
                        }
                    else:
                        last_error = f"[{ver}/{model} HTTP {resp.status}]: " + resp_text
            except Exception as e:
                last_error = f"[{ver}/{model} Exception]: " + str(e)

    err_msg = "⚠️ Gemini 연결 실패:\n```\n" + last_error[:600] + "\n

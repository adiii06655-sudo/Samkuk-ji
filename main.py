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
        "generationConfig": {
            "temperature": 0.7,
            "response_mime_type": "application/json"
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }

    # 지원이 보장된 최신 모델만 사용
    active_models = ["gemini-2.5-flash", "gemini-2.5-pro"]
    last_error = ""

    async with ClientSession() as session:
        for model in active_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            for retry in range(2):
                try:
                    async with session.post(url, json=payload, timeout=30) as resp:
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
                        elif resp.status in [429, 503]:
                            await asyncio.sleep(1)
                            continue
                        else:
                            last_error = f"HTTP {resp.status} ({model}): " + resp_text[:200]
                            break
                except Exception as e:
                    last_error = f"Exception ({model}): " + str(e)
                    await asyncio.sleep(1)

    # 일시적 장애 발생 시에도 게임이 끊기지 않는 안정적인 비상 진행
    d_val = random.randint(1, 50)
    grade = "성공" if d_val <= 25 else "실패"
    return {
        "dice_roll": d_val,
        "result_grade": grade,
        "narrative": f"{player['name']}(은)는 정세를 파악하며 신중히 발걸음을 옮깁니다. 사방에서 군마의 숨소리와 병사들의 웅성거림이 전해져옵니다.",
        "days_passed": 1,
        "stat_changes": {},
        "location": player['location'],
        "situation": player['situation']
    }

# 4. 상태창 Embed
def build_status_embed(p):
    years = p['curr_year'] - p['start_year']
    months = p['curr_month'] - 1
    days = p['curr_day'] - 1
    elapsed_str = f"{years}년 {months}개월 {days}일째"

    embed = discord.Embed(
        title=f"📜 [삼국지 TRPG] {p['name']} ({p['identity']})",
        color=0xC5A059
    )
    embed.add_field(name="📍 현 위치", value=f"**{p['location']}**", inline=True)
    embed.add_field(name="⏳ 게임 시간", value=f"서기 {p['curr_year']}년 {p['curr_month']}월 {p['curr_day']}일\n({elapsed_str})", inline=True)
    embed.add_field(name="❤️ 체력", value=f"{p['hp']} / {p['max_hp']}", inline=True)

    stat_line = f"⚔️ 무력 {p['war']} | 🧠 지력 {p['intel']} | 🚩 통솔 {p['lead']}\n🏛️ 정치 {p['pol']} | 👑 매력 {p['cha']}"
    embed.add_field(name="📊 능력치", value=stat_line, inline=False)

    assets_line = f"👥 병력: **{p['troops']}명** | 💰 소지금: **{p['gold']}냥** | 🌾 군량: **{p['rations']}포대**\n🗡️ 무기: {p['weapons']}"
    embed.add_field(name="📦 군세 및 물자", value=assets_line, inline=False)

    rel_dict = json.loads(p['relationships']) if p['relationships'] else {}
    rel_str = "\n".join([f"• **{k}**: 신뢰 {v.get('trust',0)} / 호감 {v.get('favor',0)}" for k, v in list(rel_dict.items())[:3]]) or "교류 인물 없음"
    embed.add_field(name="🤝 인물 관계", value=rel_str, inline=False)
    embed.add_field(name="📌 현재 상황", value=f"{p['situation']}", inline=False)
    embed.set_footer(text="원하는 행동을 채팅창에 자유롭게 입력하세요.")
    return embed

# 5. Discord View
class GameActionView(View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = str(user_id)

    @discord.ui.button(label="전체 상태창", style=discord.ButtonStyle.primary, emoji="📜")
    async def btn_status(self, interaction: discord.Interaction, button: Button):
        p = get_player(self.user_id)
        await interaction.response.send_message(embed=build_status_embed(p), ephemeral=True)

    @discord.ui.button(label="시간 보내기", style=discord.ButtonStyle.secondary, emoji="⏳")
    async def btn_wait(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        p = get_player(self.user_id)
        res = await query_gemini_gm(p, "한 달 동안 정세를 관망하며 휴식한다.")
        await apply_gm_result(interaction.channel, p, res)

# 6. GM 결과 반영
async def apply_gm_result(channel, p, res):
    days = res.get("days_passed", 1)
    p['curr_day'] += days
    while p['curr_day'] > 30:
        p['curr_day'] -= 30
        p['curr_month'] += 1
    while p['curr_month'] > 12:
        p['curr_month'] -= 1
        p['curr_year'] += 1
        p['age'] += 1

    changes = res.get("stat_changes", {})
    for k, v in changes.items():
        if k in p and isinstance(v, (int, float)):
            p[k] = max(0, p[k] + int(v))
    if 'max_hp' in p:
        p['hp'] = min(p['hp'], p['max_hp'])

    if res.get("location"):
        p['location'] = res["location"]
    if res.get("situation"):
        p['situation'] = res["situation"]
    if res.get("canon_event"):
        p['canon_history'] = res["canon_event"]
    if res.get("if_event"):
        p['if_history'] = res["if_event"]

    save_player(p)

    if p['hp'] <= 0 or res.get("is_game_over"):
        p['is_dead'] = 1
        save_player(p)
        desc = res.get("game_over_narrative") or res.get("narrative") or "장수가 사망했습니다."
        await channel.send(embed=discord.Embed(title="💀 [GAME OVER]", description=desc[:1800], color=0x000000))
        return

    dice_val = res.get('dice_roll', random.randint(1, 50))
    grade = res.get('result_grade', '진행')
    nar_text = res.get('narrative', '')[:1800]

    nar_embed = discord.Embed(
        title=f"🎲 주사위: [{dice_val}] ➔ 결과: [{grade}]",
        description=nar_text,
        color=0x27AE60 if "성공" in str(grade) else 0xC0392B
    )
    status_embed = build_status_embed(p)
    view = GameActionView(p['user_id'])
    await channel.send(embed=nar_embed)
    await channel.send(embed=status_embed, view=view)

# 7. 캐릭터 생성
CREATION_STEPS = {
    0: "① 장수의 **이름**을 입력해 주세요. (예: 조자룡, 유봉)",
    1: "② 시작 **연도**를 입력해 주세요. (예: 184, 190)",
    2: "③ 장수의 **나이**를 입력해 주세요. (예: 20)",
    3: "④ 장수의 **5대 능력치**를 공백으로 구분해 입력해 주세요.\n*(통솔 무력 지력 정치 매력 - 예: `80 85 70 60 75`)*",
    4: "⑤ 장수의 **시작 신분**을 입력해 주세요. (예: 일반 백성, 재야 무사, 호족)"
}

async def handle_creation(message, p, step):
    text = message.content.strip()
    if step == 0:
        p['name'] = text
        p['creation_step'] = 1
        save_player(p)
        await message.channel.send(f"이름: **'{text}'**\n\n{CREATION_STEPS[1]}")
    elif step == 1:
        p['start_year'] = int(re.sub(r'[^0-9]', '', text) or 184)
        p['curr_year'] = p['start_year']
        p['curr_month'] = 1
        p['curr_day'] = 1
        p['creation_step'] = 2
        save_player(p)
        await message.channel.send(f"연도: **서기 {p['start_year']}년**\n\n{CREATION_STEPS[2]}")
    elif step == 2:
        p['age'] = int(re.sub(r'[^0-9]', '', text) or 20)
        p['creation_step'] = 3
        save_player(p)
        await message.channel.send(f"나이: **{p['age']}세**\n\n{CREATION_STEPS[3]}")
    elif step == 3:
        nums = [int(n) for n in re.findall(r'\d+', text)]
        if len(nums) < 5:
            await message.channel.send("5개 수치를 띄어쓰기로 입력하세요. (예: `80 85 75 60 70`)")
            return
        p['lead'], p['war'], p['intel'], p['pol'], p['cha'] = nums[:5]
        p['creation_step'] = 4
        save_player(p)
        await message.channel.send(f"능력치 입력 완료!\n\n{CREATION_STEPS[4]}")
    elif step == 4:
        p['identity'] = text
        p['creation_step'] = 5
        p['troops'] = 0
        p['gold'] = 50
        p['rations'] = 3
        p['weapons'] = "목봉, 낫"
        p['location'] = "기주 상산군 외곽 촌락"
        p['hp'] = 100
        p['max_hp'] = 100
        p['renown'] = 10
        p['notoriety'] = 0
        p['relationships'] = "{}"
        p['situation'] = f"서기 {p['start_year']}년 난세에 첫발을 디딤."
        save_player(p)
        await message.channel.send("장수 등록 완료! 삼국지의 세계로 진입합니다...")
        init_res = await query_gemini_gm(p, "세상에 첫발을 내딛는 오프닝 인트로를 서술하라.")
        await apply_gm_result(message.channel, p, init_res)

# 8. 메시지 핸들러
@bot.event
async def on_ready():
    print(f"✅ {bot.user} 온라인 및 준비 완료!")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    content = message.content.strip()
    uid = str(message.author.id)
    player = get_player(uid)

    if content in ["시작", "생성", "초기화"]:
        new_p = {
            "user_id": uid, "name": "", "start_year": 184, "curr_year": 184,
            "curr_month": 1, "curr_day": 1, "age": 20, "identity": "일반 백성",
            "lead": 70, "war": 70, "intel": 70, "pol": 70, "cha": 70,
            "hp": 100, "max_hp": 100, "troops": 0, "gold": 100, "rations": 5,
            "weapons": "단도", "location": "중원", "renown": 0, "notoriety": 0,
            "situation": "방금 생성됨", "relationships": "{}", "canon_history": "",
            "if_history": "", "creation_step": 0, "is_dead": 0
        }
        save_player(new_p)
        await message.channel.send(f"삼국지 1인 TRPG에 오신 것을 환영합니다!\n\n{CREATION_STEPS[0]}")
        return

    if player and player['creation_step'] < 5:
        await handle_creation(message, player, player['creation_step'])
        return

    if not player:
        await message.channel.send("등록된 캐릭터가 없습니다. **`시작`**을 입력해 주세요.")
        return

    async with message.channel.typing():
        gm_res = await query_gemini_gm(player, content)
        await apply_gm_result(message.channel, player, gm_res)

# 9. 포트 바인딩 및 구동
async def handle_ping(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await start_web_server()
    if DISCORD_TOKEN:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())

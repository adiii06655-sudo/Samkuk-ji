import os
import sqlite3
import json
import random
import re
import discord
from discord.ext import commands
from discord.ui import View, Button
import google.generativeai as genai

# 1. 환경 변수 및 디스코드 설정
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="", intents=intents)

# 2. SQLite 데이터베이스 초기화
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

# 3. Gemini GM AI 엔진
SYSTEM_PROMPT = (
    "당신은 삼국지 정통 TRPG Game Master(GM)입니다.\n"
    "규칙:\n"
    "1. 사견을 배제하고 플레이어의 행동 결과만 객관적/역사적으로 서술합니다.\n"
    "2. 역사 표기: [정사/연의 고증] 및 [변형된 역사 - IF] 말머리를 반드시 구분해 표기합니다.\n"
    "3. 주사위 판정 (1d50): 1~3(대성공), 4~25(성공), 26~46(실패), 47~50(대실패).\n"
    "4. 행동에 따른 시간 소모(days_passed), 식량 소비, 부상/체력 소모를 계산합니다.\n"
    "5. HP 0 또는 대실패로 인한 치명상 시 게임 오버 처리 및 사후 2000년 역사 나비효과를 장엄하게 서술합니다.\n"
    "반드시 아래 JSON 형식만 반환하세요:\n"
    "{\n"
    '  "dice_roll": 20,\n'
    '  "thresholds": "대성공(1~3)/성공(4~25)/실패(26~46)/대실패(47~50)",\n'
    '  "result_grade": "성공",\n'
    '  "narrative": "스토리 서술",\n'
    '  "days_passed": 3,\n'
    '  "stat_changes": {"hp": 0, "troops": 0, "gold": 0, "rations": -2, "lead": 0, "war": 0, "intel": 0, "pol": 0, "cha": 0, "renown": 1, "notoriety": 0},\n'
    '  "location": "현재 위치",\n'
    '  "situation": "상황 요약",\n'
    '  "met_npc": {"name": "인물명", "trust_delta": 5, "favor_delta": 5},\n'
    '  "canon_event": "원전 사건",\n'
    '  "if_event": "대체역사 흐름",\n'
    '  "is_game_over": false,\n'
    '  "game_over_narrative": ""\n'
    "}"
)

async def query_gemini_gm(player, action_text):
    if not GEMINI_API_KEY:
        return {
            "dice_roll": random.randint(1, 50),
            "thresholds": "기본 판정 구간",
            "result_grade": "진행",
            "narrative": f"행동을 실행했습니다: {action_text}",
            "days_passed": 1,
            "stat_changes": {},
            "location": player['location'],
            "situation": player['situation'],
            "met_npc": None,
            "canon_event": player.get('canon_history', ''),
            "if_event": player.get('if_history', ''),
            "is_game_over": False,
            "game_over_narrative": ""
        }

    model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=SYSTEM_PROMPT)
    prompt = (
        f"[플레이어 상태]\n"
        f"이름: {player['name']} ({player['identity']}, {player['age']}세)\n"
        f"현재: 서기 {player['curr_year']}년 {player['curr_month']}월 {player['curr_day']}일\n"
        f"능력: 통솔 {player['lead']} / 무력 {player['war']} / 지력 {player['intel']} / 정치 {player['pol']} / 매력 {player['cha']}\n"
        f"체력: {player['hp']}/{player['max_hp']}, 병력: {player['troops']}명, 소지금: {player['gold']}냥, 식량: {player['rations']}포, 무기: {player['weapons']}\n"
        f"위치: {player['location']}, 위명: {player['renown']}, 악명: {player['notoriety']}\n"
        f"인물관계: {player['relationships']}\n"
        f"최근상황: {player['situation']}\n\n"
        f"[행동 입력]\n{action_text}"
    )

    response = await model.generate_content_async(prompt)
    raw = response.text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    json_str = match.group(0) if match else raw
    try:
        return json.loads(json_str)
    except Exception:
        return {
            "dice_roll": random.randint(1, 50),
            "thresholds": "기본 판정 구간",
            "result_grade": "판정 진행",
            "narrative": raw,
            "days_passed": 1,
            "stat_changes": {},
            "location": player['location'],
            "situation": player['situation'],
            "met_npc": None,
            "canon_event": player.get('canon_history', '기록 없음'),
            "if_event": player.get('if_history', '기록 없음'),
            "is_game_over": False,
            "game_over_narrative": ""
        }

# 4. 상태창 Embed
def build_status_embed(p):
    years = p['curr_year'] - p['start_year']
    months = p['curr_month'] - 1
    days = p['curr_day'] - 1
    elapsed_str = f"{years}년 {months}개월 {days}일째"

    consumption = max(1, (p['troops'] // 100) * 10)
    food_months = round(p['rations'] / consumption, 1) if consumption > 0 else 0

    embed = discord.Embed(
        title=f"📜 [삼국지 TRPG] {p['name']} ({p['identity']})",
        color=0xC5A059
    )
    embed.add_field(name="📍 현 위치", value=f"**{p['location']}**", inline=True)
    embed.add_field(name="⏳ 게임 시간", value=f"서기 {p['curr_year']}년 {p['curr_month']}월 {p['curr_day']}일\n({elapsed_str})", inline=True)
    embed.add_field(name="❤️ 체력", value=f"{p['hp']} / {p['max_hp']}", inline=True)

    stat_line = f"⚔️ 무력 {p['war']} | 🧠 지력 {p['intel']} | 🚩 통솔 {p['lead']}\n🏛️ 정치 {p['pol']} | 👑 매력 {p['cha']}"
    embed.add_field(name="📊 능력치", value=stat_line, inline=False)

    assets_line = f"👥 병력: **{p['troops']}명** | 💰 소지금: **{p['gold']}냥**\n🌾 군량: **{p['rations']}포대** (약 {food_months}개월분)\n🗡️ 무장: {p['weapons']}"
    embed.add_field(name="📦 군세 및 물자", value=assets_line, inline=False)

    rel_dict = json.loads(p['relationships']) if p['relationships'] else {}
    if rel_dict:
        rel_texts = [f"• **{name}**: 신뢰 {v.get('trust',0)} / 호감 {v.get('favor',0)}" for name, v in rel_dict.items()]
        rel_str = "\n".join(rel_texts[:5])
    else:
        rel_str = "아직 직접 교류한 인물이 없습니다."
    embed.add_field(name="🤝 인물 관계", value=rel_str, inline=False)

    embed.add_field(name="🏅 명성", value=f"위명: {p['renown']} | 악명: {p['notoriety']}", inline=True)
    embed.add_field(name="📌 현재 상황", value=f"{p['situation']}", inline=False)
    embed.set_footer(text="채팅창에 원하는 행동을 자유롭게 입력하세요.")
    return embed

# 5. Discord 버튼 인터페이스
class GameActionView(View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = str(user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("본인의 캐릭터만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="전체 상태창", style=discord.ButtonStyle.primary, emoji="📜")
    async def btn_status(self, interaction: discord.Interaction, button: Button):
        p = get_player(self.user_id)
        embed = build_status_embed(p)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="플레이어 상태", style=discord.ButtonStyle.secondary, emoji="👤")
    async def btn_player(self, interaction: discord.Interaction, button: Button):
        p = get_player(self.user_id)
        desc = (
            f"**이름:** {p['name']} ({p['age']}세, {p['identity']})\n"
            f"**건강:** 체력 {p['hp']}/{p['max_hp']}\n"
            f"**장비:** {p['weapons']}\n"
            f"**위명/악명:** {p['renown']} / {p['notoriety']}"
        )
        embed = discord.Embed(title="👤 신체 및 장비 상태", description=desc, color=0x3498DB)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="인물 관계도", style=discord.ButtonStyle.secondary, emoji="🤝")
    async def btn_relations(self, interaction: discord.Interaction, button: Button):
        p = get_player(self.user_id)
        rel_dict = json.loads(p['relationships']) if p['relationships'] else {}
        if not rel_dict:
            text = "아직 직접 만난 인물이 없습니다."
        else:
            text = "\n".join([f"• **{k}**: 신뢰 {v.get('trust', 0)} / 호감 {v.get('favor', 0)}" for k, v in rel_dict.items()])
        embed = discord.Embed(title="🤝 인물 관계도", description=text, color=0x2ECC71)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="시간 보내기", style=discord.ButtonStyle.secondary, emoji="⏳")
    async def btn_wait(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        p = get_player(self.user_id)
        res = await query_gemini_gm(p, "한 달 동안 정세를 관망하며 시간을 보낸다.")
        await apply_gm_result(interaction.channel, p, res)

    @discord.ui.button(label="역사 비교기", style=discord.ButtonStyle.danger, emoji="⚖️")
    async def btn_history(self, interaction: discord.Interaction, button: Button):
        p = get_player(self.user_id)
        canon = p.get('canon_history') or "원전 기록 없음"
        if_hist = p.get('if_history') or "원전 흐름 유지 중"
        embed = discord.Embed(title="⚖️ 역사 비교기 (정사/연의 vs IF)", color=0xE74C3C)
        embed.add_field(name="[정사/연의 고증]", value=canon, inline=False)
        embed.add_field(name="[변형된 역사 - IF]", value=if_hist, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# 6. GM 판정 결과 반영
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
        if k in p:
            p[k] = max(0, p[k] + v)
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

    met = res.get("met_npc")
    if met and isinstance(met, dict) and met.get("name"):
        rel = json.loads(p['relationships']) if p['relationships'] else {}
        name = met["name"]
        curr = rel.get(name, {"trust": 10, "favor": 10})
        curr["trust"] = max(0, min(100, curr.get("trust", 10) + met.get("trust_delta", 0)))
        curr["favor"] = max(0, min(100, curr.get("favor", 10) + met.get("favor_delta", 0)))
        rel[name] = curr
        p['relationships'] = json.dumps(rel, ensure_ascii=False)

    save_player(p)

    if p['hp'] <= 0 or res.get("is_game_over"):
        p['is_dead'] = 1
        save_player(p)
        go_desc = res.get("game_over_narrative") or res.get("narrative")
        embed = discord.Embed(title="💀 [GAME OVER - 장수의 최후]", description=go_desc, color=0x000000)
        await channel.send(embed=embed)
        return

    dice_title = f"🎲 주사위: [{res.get('dice_roll', '?')}] ➔ 결과: [{res.get('result_grade', '진행')}]"
    thresh_desc = f"*판정:* `{res.get('thresholds', '1~50')}`\n\n{res.get('narrative', '')}"

    nar_embed = discord.Embed(
        title=dice_title,
        description=thresh_desc,
        color=0x27AE60 if "성공" in str(res.get('result_grade')) else 0xC0392B
    )
    status_embed = build_status_embed(p)
    view = GameActionView(p['user_id'])
    await channel.send(embed=nar_embed)
    await channel.send(embed=status_embed, view=view)

# 7. 캐릭터 생성 단계
CREATION_STEPS = {
    0: "① 장수의 **이름**을 입력해 주세요. (예: 조자룡, 유봉, 강유)",
    1: "② 게임을 시작할 **시작 연도**를 입력해 주세요. (예: 184 [황건적], 190 [반동탁], 208 [적벽대전])",
    2: "③ 장수의 **나이**를 입력해 주세요. (예: 22)",
    3: "④ 장수의 **5대 능력치**를 공백으로 구분해 입력해 주세요.\n*(통솔 무력 지력 정치 매력 - 예: `80 85 70 60 75`)*",
    4: "⑤ 장수의 **시작 신분**을 입력해 주세요.\n*(예: 일반 백성, 재야 무사, 호족 자제, 현령, 기마병)*"
}

async def handle_creation(message, p, step):
    text = message.content.strip()

    if step == 0:
        p['name'] = text
        p['creation_step'] = 1
        save_player(p)
        await message.channel.send(f"이름: **'{text}'**\n\n{CREATION_STEPS[1]}")
    elif step == 1:
        year = int(re.sub(r'[^0-9]', '', text) or 190)
        p['start_year'] = year
        p['curr_year'] = year
        p['curr_month'] = 1
        p['curr_day'] = 1
        p['creation_step'] = 2
        save_player(p)
        await message.channel.send(f"시작 연도: **서기 {year}년**\n\n{CREATION_STEPS[2]}")
    elif step == 2:
        age = int(re.sub(r'[^0-9]', '', text) or 20)
        p['age'] = age
        p['creation_step'] = 3
        save_player(p)
        await message.channel.send(f"나이: **{age}세**\n\n{CREATION_STEPS[3]}")
    elif step == 3:
        nums = [int(n) for n in re.findall(r'\d+', text)]
        if len(nums) < 5:
            await message.channel.send("5개 능력치 수치를 순서대로 띄어쓰기로 입력하세요. (예: `80 85 75 60 70`)")
            return
        p['lead'], p['war'], p['intel'], p['pol'], p['cha'] = nums[:5]
        p['creation_step'] = 4
        save_player(p)
        await message.channel.send(f"능력치: **통솔 {p['lead']} / 무력 {p['war']} / 지력 {p['intel']} / 정치 {p['pol']} / 매력 {p['cha']}**\n\n{CREATION_STEPS[4]}")
    elif step == 4:
        identity = text
        p['identity'] = identity
        p['creation_step'] = 5

        if "백성" in identity or "농민" in identity:
            p['troops'] = 0
            p['gold'] = 50
            p['rations'] = 3
            p['weapons'] = "목봉, 낫"
            p['location'] = "기주 상산군 외곽 촌락"
        elif "무사" in identity or "용병" in identity:
            p['troops'] = 10
            p['gold'] = 200
            p['rations'] = 10
            p['weapons'] = "환두대도, 가죽 갑옷"
            p['location'] = "낙양 저잣거리"
        elif "호족" in identity or "현령" in identity or "군관" in identity:
            p['troops'] = 100
            p['gold'] = 1000
            p['rations'] = 50
            p['weapons'] = "철검, 연환갑, 군마"
            p['location'] = "형주 양양성 관아"
        else:
            p['troops'] = 20
            p['gold'] = 300
            p['rations'] = 15
            p['weapons'] = "철창"
            p['location'] = "중원 소도시"

        p['hp'] = 100
        p['max_hp'] = 100
        p['renown'] = 10
        p['notoriety'] = 0
        p['relationships'] = "{}"
        p['situation'] = f"서기 {p['start_year']}년, {identity} 신분으로 난세에 첫발을 디딤."
        p['canon_history'] = f"서기 {p['start_year']}년 한 황실의 쇠락 시기."
        p['if_history'] = f"{p['name']} 등장."
        save_player(p)

        await message.channel.send("장수 등록 완료! 시작 인트로를 구성 중입니다...")
        init_res = await query_gemini_gm(p, f"서기 {p['start_year']}년, {p['age']}세 {p['identity']} 신분으로 세상에 나서는 첫 인트로를 서술하라.")
        await apply_gm_result(message.channel, p, init_res)

# 8. 메시지 핸들러
@bot.event
async def on_ready():
    print(f"✅ {bot.user} 봇이 성공적으로 로그인되었습니다!")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.strip()
    uid = str(message.author.id)
    player = get_player(uid)

    if content in ["시작", "생성", "초기화"]:
        new_p = {
            "user_id": uid, "name": "", "start_year": 190, "curr_year": 190,
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
        await message.channel.send("등록된 캐릭터가 없습니다. **`시작`**을 입력해 캐릭터를 생성하세요.")
        return

    if player['is_dead']:
        await message.channel.send("사망한 장수입니다. 다시 시작하려면 **`시작`**을 입력하세요.")
        return

    if content in ["상태", "상태창"]:
        embed = build_status_embed(player)
        view = GameActionView(uid)
        await message.channel.send(embed=embed, view=view)
        return

    async with message.channel.typing():
        gm_res = await query_gemini_gm(player, content)
        await apply_gm_result(message.channel, player, gm_res)

# 9. 봇 실행 구동
if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("[에러] DISCORD_TOKEN 환경변수가 설정되지 않았습니다.")

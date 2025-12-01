import os
import asyncio
import json
from typing import Dict, List

import discord
from discord.ext import commands
from discord import app_commands
import feedparser

# ---------------- 설정 ----------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DATA_FILE = "rss_data.json"

intents = discord.Intents.default()
intents.message_content = True  # prefix 명령어 사용을 위해 필요

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- 저장소 유틸 ----------------
def load_data() -> Dict:
    """
    rss_data.json을 읽어서 Dict로 반환.
    파일이 없거나 형식이 잘못되었으면 기본 구조로 초기화.
    """
    if not os.path.exists(DATA_FILE):
        return {"feeds": []}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # 파일이 깨졌거나 비어있을 때
        return {"feeds": []}

    # feeds 키가 없거나 list가 아니면 초기화
    if "feeds" not in data or not isinstance(data["feeds"], list):
        data["feeds"] = []

    return data
    
def save_data(data: Dict):
    """
    rss_data.json 저장.
    """
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------------- 기본 명령어 ----------------
@bot.event
async def on_ready():
    if not hasattr(bot, "synced"):
        await bot.tree.sync()
        bot.synced = True
        print(f"Synced {len(synced)} slash command(s)")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")


@bot.tree.command(name="ping", description="eu-ssya-bot 상태 체크")
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message("pong from eu-ssya-bot")

# ---------------- Slash 명령어 그룹: /rss ... ----------------
rss_group = app_commands.Group(
    name="rss",
    description="RSS 구독 관리 명령어"
)

@rss_group.command(name="add", description="현재 채널에 RSS 피드를 등록합니다.")
@app_commands.describe(url="RSS 피드 URL (예: https://xxx.tistory.com/rss)")
async def rss_add_slash(interaction: discord.Interaction, url: str):
    """
    /rss add
    """
    data = load_data()

    # 중복 체크
    for feed in data["feeds"]:
        if feed["url"] == url and feed["channel_id"] == interaction.channel.id:
            await interaction.response.send_message(
                "이 채널에는 이미 이 RSS 피드가 등록되어 있습니다.",
                ephemeral=True,
            )
            return

    parsed = feedparser.parse(url)
    last_entry_id = None
    if parsed.entries:
        entry = parsed.entries[0]
        last_entry_id = getattr(entry, "id", None) or getattr(entry, "link", None)

    data["feeds"].append(
        {
            "url": url,
            "channel_id": interaction.channel.id,
            "last_entry_id": last_entry_id,
        }
    )
    save_data(data)

    await interaction.response.send_message(
        f"RSS 등록 완료:\n`{url}` → {interaction.channel.mention}"
    )

@rss_group.command(name="list", description="현재 채널에 등록된 RSS 목록을 보여줍니다.")
async def rss_list_slash(interaction: discord.Interaction):
    """
    /rss list
    """
    data = load_data()
    feeds = [f for f in data["feeds"] if f["channel_id"] == interaction.channel.id]

    if not feeds:
        await interaction.response.send_message("이 채널에 등록된 RSS가 없습니다.")
        return

    lines: List[str] = []
    for idx, feed in enumerate(feeds, start=1):
        lines.append(f"{idx}. {feed['url']}")

    msg = "등록된 RSS 목록:\n" + "\n".join(lines)
    await interaction.response.send_message(msg)


@rss_group.command(name="remove", description="현재 채널에서 특정 RSS를 제거합니다.")
@app_commands.describe(url="삭제할 RSS 피드 URL")
async def rss_remove_slash(interaction: discord.Interaction, url: str):
    """
    /rss remove
    """
    data = load_data()
    before = len(data["feeds"])

    data["feeds"] = [
        f for f in data["feeds"]
        if not (f["url"] == url and f["channel_id"] == interaction.channel.id)
    ]
    after = len(data["feeds"])

    save_data(data)

    if before == after:
        await interaction.response.send_message(
            "해당 URL은 이 채널에 등록되어 있지 않습니다."
        )
    else:
        await interaction.response.send_message(f"RSS 삭제 완료: `{url}`")

# 그룹을 트리에 등록
bot.tree.add_command(rss_group)

# ---------------- RSS 폴링 루프 ----------------
async def rss_loop():
    """
    일정 간격으로 모든 등록된 RSS 피드를 확인하고,
    새 글이 있으면 디스코드 채널에 전송한다.
    """
    await bot.wait_until_ready()
    print("RSS loop started")

    while not bot.is_closed():
        print("RSS loop tick")

        data = load_data()
        feeds: List[Dict] = data.get("feeds") or []   # ← 여기 방어

        changed = False

        for feed in feeds:
            url = feed["url"]
            channel_id = feed["channel_id"]
            last_entry_id = feed.get("last_entry_id")

            print(f"  checking feed: {url} (channel={channel_id})")

            parsed = feedparser.parse(url)
            entries = parsed.entries

            if not entries:
                print("    no entries")
                continue

            new_entries = []
            for entry in entries:
                entry_id = getattr(entry, "id", None) or getattr(entry, "link", None)
                if last_entry_id is not None and entry_id == last_entry_id:
                    break
                new_entries.append(entry)

            if new_entries:
                print(f"    found {len(new_entries)} new entries")
                new_entries.reverse()

                channel = bot.get_channel(channel_id)
                if channel is None:
                    print("    channel not found or inaccessible")
                    continue

                for entry in new_entries:
                    title = getattr(entry, "title", "제목 없음")
                    link = getattr(entry, "link", "")
                    await channel.send(f"[새 글] {title}\n{link}")

                latest = entries[0]
                feed["last_entry_id"] = getattr(latest, "id", None) or getattr(latest, "link", None)
                changed = True
            else:
                print("    no new entries")

        if changed:
            save_data({"feeds": feeds})

        await asyncio.sleep(300)


# ---------------- 엔트리 포인트 ----------------
async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN 환경 변수가 설정되어 있지 않습니다.")

    async with bot:
        bot.loop.create_task(rss_loop())
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
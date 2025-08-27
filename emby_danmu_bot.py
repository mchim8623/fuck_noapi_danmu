import os
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 从环境变量获取配置
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_BASE_URL = "http://emby.com:7768/api/ui"
#emby.com替换为你的御坂
USERNAME = os.getenv('DANMU_USERNAME', 'admin')
PASSWORD = os.getenv('DANMU_PASSWORD', 'password')
#替换为你的用户名和密码

# 全局变量存储访问令牌
access_token = None
token_type = None

async def get_token():
    """获取API访问令牌"""
    global access_token, token_type
    try:
        async with httpx.AsyncClient() as client:
            data = {
                "username": USERNAME,
                "password": PASSWORD
            }
            response = await client.post(f"{API_BASE_URL}/auth/token", data=data)
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data["access_token"]
            token_type = token_data["token_type"]
            logger.info("成功获取访问令牌")
            return True
    except Exception as e:
        logger.error(f"获取令牌失败: {e}")
        return False

async def ensure_token():
    """确保有有效的访问令牌"""
    if access_token is None:
        return await get_token()
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理/start命令"""
    welcome_text = (
        "欢迎使用弹幕机器人！\n\n"
        "使用以下命令操作：\n"
        "/search <关键词> - 搜索剧集\n"
        "/check [任务ID] - 查看任务状态\n"
        "/help - 显示帮助信息\n"
        "或者直接发送关键词进行搜索"
    )
    await update.message.reply_text(welcome_text)

async def search_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """搜索媒体内容"""
    # 确保有有效的令牌
    if not await ensure_token():
        await update.message.reply_text("无法连接到服务器，请稍后再试。")
        return

    # 获取搜索关键词
    if context.args:
        keyword = " ".join(context.args)
    else:
        # 如果是直接发送的消息而不是命令
        if update.message.text and not update.message.text.startswith('/'):
            keyword = update.message.text
        else:
            await update.message.reply_text("请提供搜索关键词，例如: /search 数码宝贝")
            return

    await update.message.reply_text(f"正在搜索: {keyword}...")

    try:
        # 设置请求头 - 确保在 token_type 和 access_token 之间有空格
        headers = {
            "Authorization": f"{token_type} {access_token}"
        }

        # 发送搜索请求
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/search/provider",
                params={"keyword": keyword},
                headers=headers
            )
            response.raise_for_status()
            search_results = response.json()

        # 处理搜索结果
        if not search_results.get("results"):
            await update.message.reply_text("未找到相关结果，请尝试其他关键词。")
            return

        # 存储搜索结果供回调使用
        context.user_data["search_results"] = search_results["results"]
        context.user_data["current_page"] = 0
        
        # 显示第一页结果
        await show_search_page(update, context, 0)

    except Exception as e:
        logger.error(f"搜索失败: {e}")
        await update.message.reply_text("搜索过程中出现错误，请稍后再试。")

async def show_search_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    """显示搜索结果页面"""
    search_results = context.user_data.get("search_results", [])
    total_results = len(search_results)
    results_per_page = 10
    total_pages = (total_results + results_per_page - 1) // results_per_page
    
    # 确保页码在有效范围内
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1
    
    context.user_data["current_page"] = page
    
    # 计算当前页的结果范围
    start_idx = page * results_per_page
    end_idx = min(start_idx + results_per_page, total_results)
    
    # 创建内联键盘按钮
    keyboard = []
    for i in range(start_idx, end_idx):
        result = search_results[i]
        title = result.get("title", "未知标题")
        year = result.get("year", "未知年份")
        provider = result.get("provider", "未知来源")
        button_text = f"{title} ({year}) - {provider}"
        # 由于Telegram按钮文本长度限制，可能需要截断
        if len(button_text) > 40:
            button_text = button_text[:37] + "..."
        
        callback_data = f"import_{i}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    # 添加上一页和下一页按钮
    navigation_buttons = []
    if page > 0:
        navigation_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"page_{page-1}"))
    if page < total_pages - 1:
        navigation_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"page_{page+1}"))
    
    if navigation_buttons:
        keyboard.append(navigation_buttons)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 发送或编辑消息
    message_text = f"找到 {total_results} 个结果 (第 {page+1}/{total_pages} 页)，请选择要导入弹幕的剧集:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)

async def handle_page_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理翻页回调"""
    query = update.callback_query
    await query.answer()
    
    # 获取目标页码
    page = int(query.data.split("_")[1])
    
    # 显示目标页码的结果
    await show_search_page(update, context, page)

async def import_danmu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理导入弹幕的回调"""
    query = update.callback_query
    await query.answer()

    # 获取选择的剧集索引
    index = int(query.data.split("_")[1])
    search_results = context.user_data.get("search_results", [])
    
    if index >= len(search_results):
        await query.edit_message_text("无效的选择，请重新搜索。")
        return

    selected_media = search_results[index]
    await query.edit_message_text(f"正在导入: {selected_media.get('title', '未知标题')}...")

    try:
        # 确保有有效的令牌
        if not await ensure_token():
            await query.edit_message_text("无法连接到服务器，请稍后再试。")
            return

        # 设置请求头 - 确保在 token_type 和 access_token 之间有空格
        headers = {
            "Authorization": f"{token_type} {access_token}",
            "Content-Type": "application/json"
        }

        # 准备导入数据
        import_data = {
            "provider": selected_media.get("provider"),
            "media_id": selected_media.get("mediaId"),
            "anime_title": selected_media.get("title"),
            "type": selected_media.get("type"),
            "season": selected_media.get("season"),
            "image_url": selected_media.get("imageUrl"),
            "douban_id": selected_media.get("douban_id"),
            "current_episode_index": selected_media.get("currentEpisodeIndex")
        }

        # 发送导入请求
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_BASE_URL}/import",
                json=import_data,
                headers=headers
            )

        # 处理响应
        if response.status_code == 202:
            result = response.json()
            await query.edit_message_text(
                f"✅ 导入任务已提交！\n\n"
                f"标题: {selected_media.get('title')}\n"
                f"类型: {selected_media.get('type')}\n"
                f"年份: {selected_media.get('year')}\n"
                f"来源: {selected_media.get('provider')}\n\n"
                f"消息: {result.get('message')}\n"
                f"任务ID: {result.get('task_id')}"
            )
        elif response.status_code == 409:
            await query.edit_message_text(
                f"⚠️ 服务器中已存在此弹幕\n\n"
                f"标题: {selected_media.get('title')}\n"
                f"类型: {selected_media.get('type')}\n"
                f"年份: {selected_media.get('year')}\n"
                f"来源: {selected_media.get('provider')}"
            )
        else:
            await query.edit_message_text(f"导入失败，服务器返回状态码: {response.status_code}")

    except Exception as e:
        logger.error(f"导入失败: {e}")
        await query.edit_message_text("导入过程中出现错误，请稍后再试。")

async def check_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看任务状态"""
    # 确保有有效的令牌
    if not await ensure_token():
        await update.message.reply_text("无法连接到服务器，请稍后再试。")
        return

    # 获取任务ID参数（如果有）
    task_id = context.args[0] if context.args else None

    try:
        # 设置请求头 - 确保在 token_type 和 access_token 之间有空格
        headers = {
            "Authorization": f"{token_type} {access_token}"
        }

        # 发送获取任务列表请求
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/tasks",
                headers=headers
            )
            response.raise_for_status()
            tasks = response.json()

        # 如果没有任务
        if not tasks:
            await update.message.reply_text("当前没有任务。")
            return

        # 如果指定了任务ID，查找特定任务
        if task_id:
            found_task = None
            for task in tasks:
                if task.get("task_id") == task_id:
                    found_task = task
                    break
            
            if found_task:
                status_emoji = "🟢" if found_task.get("status") == "已完成" else "🟡" if found_task.get("status") == "运行中" else "🔴"
                message = (
                    f"{status_emoji} 任务详情\n\n"
                    f"任务ID: {found_task.get('task_id')}\n"
                    f"标题: {found_task.get('title')}\n"
                    f"状态: {found_task.get('status')}\n"
                    f"进度: {found_task.get('progress')}%\n"
                    f"描述: {found_task.get('description')}"
                )
                await update.message.reply_text(message)
            else:
                await update.message.reply_text(f"未找到ID为 {task_id} 的任务。")
            return

        # 如果没有指定任务ID，显示最近的任务
        recent_tasks = tasks[:5]  # 显示最近5个任务
        
        message = "📋 最近任务列表:\n\n"
        for i, task in enumerate(recent_tasks, 1):
            status_emoji = "🟢" if task.get("status") == "已完成" else "🟡" if task.get("status") == "运行中" else "🔴"
            message += (
                f"{i}. {status_emoji} {task.get('title')}\n"
                f"   状态: {task.get('status')} ({task.get('progress')}%)\n"
                f"   ID: {task.get('task_id')}\n\n"
            )
        
        message += "使用 /check <任务ID> 查看特定任务的详细信息。"
        await update.message.reply_text(message)

    except Exception as e:
        logger.error(f"获取任务列表失败: {e}")
        await update.message.reply_text("获取任务列表过程中出现错误，请稍后再试。")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示帮助信息"""
    help_text = (
        "🤖 弹幕机器人使用指南\n\n"
        "1. 使用 /search <关键词> 搜索剧集\n"
        "2. 或者直接发送关键词进行搜索\n"
        "3. 从搜索结果中选择要导入弹幕的剧集\n"
        "4. 机器人会尝试导入弹幕并返回结果\n"
        "5. 使用 /check 查看最近任务列表\n"
        "6. 使用 /check <任务ID> 查看特定任务详情\n\n"
        "示例:\n"
        "/search 数码宝贝\n"
        "/check dca214c5-73fb-4b4a-97f5-cfcf35e80094\n"
        "或直接发送: 数码宝贝"
    )
    await update.message.reply_text(help_text)

def main():
    """启动机器人"""
    # 创建Application实例
    application = Application.builder().token(BOT_TOKEN).build()

    # 添加处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("search", search_media))
    application.add_handler(CommandHandler("check", check_task))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_media))
    application.add_handler(CallbackQueryHandler(handle_page_navigation, pattern="^page_"))
    application.add_handler(CallbackQueryHandler(import_danmu, pattern="^import_"))

    # 启动机器人
    logger.info("机器人启动中...")
    application.run_polling()

if __name__ == "__main__":
    main()
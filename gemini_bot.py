import os
import logging
import datetime
import re
import tempfile
import asyncio
import shutil
from pathlib import Path
from typing import Optional, Dict, List
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import google.generativeai as genai
from fpdf import FPDF, XPos, YPos
import markdown
import html

# ------------------------- #
#       НАСТРОЙКИ И ЛОГИ    #
# ------------------------- #

load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Конфигурация
MSK_TZ = datetime.timezone(datetime.timedelta(hours=3))
BOT_ALIAS = "геминидак"
BOT_USERNAME = "geminiduck_bot"

# Параметры
MAX_TEXT_RESPONSE = 500      # Максимум для текстового ответа
MAX_TOTAL_CHARS = 6000       # Общий лимит
TEMP_FILE_LIFETIME = 3600    # Время жизни временных файлов (1 час)

# ------------------------- #
#       МЕНЕДЖЕР ФАЙЛОВ     #
# ------------------------- #

class FileManager:
    """Управление временными файлами и директориями пользователей"""
    
    def __init__(self):
        self.base_dir = Path(tempfile.gettempdir()) / "geminiduck"
        self.base_dir.mkdir(exist_ok=True)
        logger.info(f"Базовая директория: {self.base_dir}")
    
    def get_user_base_dir(self, user_id: int) -> Path:
        """Возвращает базовую директорию пользователя"""
        user_dir = self.base_dir / f"user_{user_id}"
        user_dir.mkdir(exist_ok=True)
        return user_dir
    
    def get_user_temp_dir(self, user_id: int) -> Path:
        """Возвращает временную директорию пользователя для текущей сессии"""
        temp_dir = self.get_user_base_dir(user_id) / "temp"
        temp_dir.mkdir(exist_ok=True)
        # Очищаем старые файлы в этой директории
        self.cleanup_dir(temp_dir, max_age_seconds=3600)
        return temp_dir
    
    def get_user_history_dir(self, user_id: int) -> Path:
        """Возвращает директорию истории пользователя"""
        history_dir = self.get_user_base_dir(user_id) / "history"
        history_dir.mkdir(exist_ok=True)
        return history_dir
    
    def create_temp_file(self, user_id: int, prefix: str = "", extension: str = "") -> Path:
        """Создает уникальный временный файл"""
        temp_dir = self.get_user_temp_dir(user_id)
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        filename = f"{prefix}{timestamp}"
        if extension:
            filename += f".{extension}"
        return temp_dir / filename
    
    def save_markdown(self, user_id: int, content: str, filename: str = "response") -> Path:
        """Сохраняет текст в Markdown файл"""
        md_file = self.create_temp_file(user_id, f"md_{filename}_", "md")
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(content)
        return md_file
    
    def save_html(self, user_id: int, content: str, filename: str = "response") -> Path:
        """Сохраняет текст в HTML файл"""
        html_file = self.create_temp_file(user_id, f"html_{filename}_", "html")
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(content)
        return html_file
    
    def cleanup_dir(self, directory: Path, max_age_seconds: int = 3600):
        """Очищает директорию от старых файлов"""
        try:
            now = datetime.datetime.now()
            for file_path in directory.glob("*"):
                if file_path.is_file():
                    file_age = now - datetime.datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_age.total_seconds() > max_age_seconds:
                        file_path.unlink()
        except Exception as e:
            logger.error(f"Ошибка очистки директории {directory}: {e}")
    
    def cleanup_user_files(self, user_id: int):
        """Полностью очищает файлы пользователя"""
        try:
            user_dir = self.get_user_base_dir(user_id)
            if user_dir.exists():
                # Очищаем только временные файлы, историю оставляем
                temp_dir = user_dir / "temp"
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                # Пересоздаем пустую temp директорию
                temp_dir.mkdir(exist_ok=True)
        except Exception as e:
            logger.error(f"Ошибка очистки файлов пользователя {user_id}: {e}")
    
    def cleanup_all_old_files(self, max_age_hours: int = 24):
        """Очищает все старые файлы всех пользователей"""
        try:
            now = datetime.datetime.now()
            deleted_count = 0
            
            for user_dir in self.base_dir.iterdir():
                if user_dir.is_dir():
                    # Очищаем temp директории
                    temp_dir = user_dir / "temp"
                    if temp_dir.exists():
                        self.cleanup_dir(temp_dir, max_age_seconds=max_age_hours * 3600)
                    
                    # Очищаем историю старше 7 дней
                    history_dir = user_dir / "history"
                    if history_dir.exists():
                        for file_path in history_dir.glob("*"):
                            if file_path.is_file():
                                file_age = now - datetime.datetime.fromtimestamp(file_path.stat().st_mtime)
                                if file_age.total_seconds() > (7 * 24 * 3600):  # 7 дней
                                    file_path.unlink()
                                    deleted_count += 1
            
            logger.info(f"Очищено {deleted_count} старых файлов истории")
            
        except Exception as e:
            logger.error(f"Ошибка глобальной очистки файлов: {e}")

# ------------------------- #
#   MARKDOWN ПРОЦЕССОР     #
# ------------------------- #

class MarkdownProcessor:
    """Обработка и форматирование Markdown текста"""
    
    @staticmethod
    def clean_markdown(text: str) -> str:
        """Очищает и форматирует Markdown текст"""
        # Убираем лишние переводы строк
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Заменяем проблемные символы
        replacements = {
            '`': "'",      # Заменяем обратные кавычки на обычные
            '```': '```\n', # Добавляем перевод строки после блоков кода
            '\t': '    ',   # Заменяем табуляцию на пробелы
        }
        
        for old, new in replacements.items():
            text = text.replace(old, new)
        
        return text
    
    @staticmethod
    def markdown_to_html(md_text: str) -> str:
        """Конвертирует Markdown в HTML"""
        try:
            # Очищаем Markdown
            clean_md = MarkdownProcessor.clean_markdown(md_text)
            
            # Конвертируем в HTML
            html_content = markdown.markdown(
                clean_md,
                extensions=['extra', 'codehilite', 'tables']
            )
            
            return html_content
        except Exception as e:
            logger.error(f"Ошибка конвертации Markdown в HTML: {e}")
            # Возвращаем очищенный текст в HTML обертке
            return f"<pre>{html.escape(md_text)}</pre>"
    
    @staticmethod
    def markdown_to_plain_text(md_text: str) -> str:
        """Конвертирует Markdown в простой текст"""
        # Удаляем Markdown разметку
        text = md_text
        
        # Удаляем Markdown синтаксис
        patterns = [
            (r'#+\s*', ''),        # Заголовки
            (r'\*\*(.*?)\*\*', r'\1'),  # Жирный текст
            (r'\*(.*?)\*', r'\1'),      # Курсив
            (r'`(.*?)`', r'\1'),        # Встроенный код
            (r'```.*?\n(.*?)```', r'\1'), # Блоки кода
            (r'!\[.*?\]\(.*?\)', ''),   # Изображения
            (r'\[(.*?)\]\(.*?\)', r'\1'), # Ссылки
            (r'^\s*-\s*', '• '),        # Списки
            (r'^\s*\*\s*', '• '),
            (r'^\s*\d+\.\s*', ''),
        ]
        
        for pattern, replacement in patterns:
            text = re.sub(pattern, replacement, text, flags=re.MULTILINE | re.DOTALL)
        
        return text

# ------------------------- #
#      ГЕНЕРАТОР PDF       #
# ------------------------- #

class PDFGenerator:
    @staticmethod
    def create_pdf_from_markdown(md_text: str, user_id: int, query: str = "") -> Optional[Path]:
        """Создает PDF файл из Markdown текста (надежная версия)"""
        try:
            file_manager = FileManager()
            
            # Сначала сохраняем Markdown во временный файл
            md_file = file_manager.save_markdown(user_id, md_text, "source")
            
            # Конвертируем Markdown в простой текст
            plain_text = MarkdownProcessor.markdown_to_plain_text(md_text)
            
            # Создаем PDF файл
            pdf_file = file_manager.create_temp_file(user_id, "pdf_", "pdf")
            
            pdf = FPDF()
            pdf.add_page()

            
            pdf.set_auto_page_break(auto=True, margin=15)
            # --- Unicode font (кириллица) ---
            font_regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            font_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

            pdf.add_font("DejaVu", "", font_regular, uni=True)
            pdf.add_font("DejaVu", "B", font_bold, uni=True)
            pdf.set_font("DejaVu", size=12)
            # --- end font setup ---

            # Используем стандартные шрифты Arial (поддерживаются в FPDF)
            # Сначала устанавливаем шрифт Arial для латиницы
            pdf.set_font("DejaVu", size=12)
            
            # Заголовок
            pdf.set_font_size(16)
            pdf.cell(200, 10, text="GeminiDuck Bot", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
            
            # Дата и информация
            pdf.set_font_size(10)
            pdf.cell(200, 8, text=f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.cell(200, 8, text=f"User ID: {user_id}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            
            # Добавляем разделитель
            pdf.ln(5)
            pdf.cell(200, 1, text="", new_x=XPos.LMARGIN, new_y=YPos.NEXT, border='T')
            pdf.ln(10)
            
            # Вопрос (если есть)
            if query:
                pdf.set_font("DejaVu", 'B', 12)
                pdf.cell(200, 10, text="Question:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_font("DejaVu", '', 10)
                
                # Обрабатываем вопрос
                query_lines = PDFGenerator._wrap_text(query[:300], 80)
                for line in query_lines:
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(0, 8, text=line)
                pdf.ln(5)
            
            # Ответ
            pdf.set_font("DejaVu", 'B', 12)
            pdf.cell(200, 10, text="Answer:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("DejaVu", '', 10)
            
            # Разбиваем текст на строки
            lines = PDFGenerator._wrap_text(plain_text, 80)
            
            # Ограничиваем количество строк
            max_lines = 200
            for i, line in enumerate(lines[:max_lines]):
                # Добавляем отступ для списков
                if line.startswith('• ') or line.startswith('- '):
                    pdf.cell(10)  # Отступ
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(0, 8, text=line[2:])
                else:
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(0, 8, text=line)
            
            if len(lines) > max_lines:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, 8, text=f"\n[Document truncated. Full text has {len(lines)} lines]")
            
            # Сохраняем PDF
            pdf.output(str(pdf_file))
            
            # Удаляем временный markdown файл
            if md_file.exists():
                md_file.unlink()
            
            logger.info(f"PDF успешно создан: {pdf_file}, размер: {pdf_file.stat().st_size} байт")
            return pdf_file
            
        except Exception as e:
            logger.error(f"Ошибка создания PDF: {e}", exc_info=True)
            return None
    
    @staticmethod
    def _wrap_text(text: str, max_width: int) -> List[str]:
        """Разбивает текст на строки фиксированной ширины"""
        lines = []
        
        for paragraph in text.split('\n'):
            words = paragraph.split(' ')
            current_line = []
            current_length = 0
            
            for word in words:
                word_length = len(word)
                
                # Если слово слишком длинное, разбиваем его
                if word_length > max_width:
                    if current_line:
                        lines.append(' '.join(current_line))
                        current_line = []
                        current_length = 0
                    
                    # Разбиваем длинное слово на части
                    for i in range(0, word_length, max_width):
                        lines.append(word[i:i + max_width])
                else:
                    if current_length + word_length + len(current_line) > max_width:
                        lines.append(' '.join(current_line))
                        current_line = [word]
                        current_length = word_length
                    else:
                        current_line.append(word)
                        current_length += word_length
            
            if current_line:
                lines.append(' '.join(current_line))
        
        return lines

# ------------------------- #
#    ГЕНЕРАТОР HTML        #
# ------------------------- #

class HTMLGenerator:
    @staticmethod
    def create_html_from_markdown(md_text: str, user_id: int, query: str = "") -> Optional[Path]:
        """Создает HTML файл из Markdown текста"""
        try:
            file_manager = FileManager()
            
            # Конвертируем Markdown в HTML
            html_content = MarkdownProcessor.markdown_to_html(md_text)
            
            # Создаем полноценный HTML документ
            full_html = HTMLGenerator._create_html_document(
                html_content=html_content,
                user_id=user_id,
                query=query
            )
            
            # Сохраняем HTML файл
            html_file = file_manager.save_html(user_id, full_html, "response")
            
            logger.info(f"HTML успешно создан: {html_file}, размер: {html_file.stat().st_size} байт")
            return html_file
            
        except Exception as e:
            logger.error(f"Ошибка создания HTML: {e}")
            return None
    
    @staticmethod
    def _create_html_document(html_content: str, user_id: int, query: str = "") -> str:
        """Создает полный HTML документ с оформлением"""
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ответ GeminiDuck Bot</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }}
        
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 300;
        }}
        
        .header .subtitle {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        
        .content {{
            padding: 40px;
        }}
        
        .info-bar {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 30px;
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 15px;
        }}
        
        .info-item {{
            flex: 1;
            min-width: 200px;
        }}
        
        .info-label {{
            font-weight: 600;
            color: #667eea;
            margin-bottom: 5px;
        }}
        
        .question-box {{
            background: #e8f4fd;
            border-left: 5px solid #2196F3;
            padding: 20px;
            margin-bottom: 30px;
            border-radius: 0 10px 10px 0;
        }}
        
        .question-box h3 {{
            color: #1976D2;
            margin-bottom: 10px;
        }}
        
        .response-content {{
            line-height: 1.8;
        }}
        
        .response-content h1, 
        .response-content h2, 
        .response-content h3 {{
            color: #333;
            margin: 25px 0 15px 0;
        }}
        
        .response-content p {{
            margin-bottom: 15px;
        }}
        
        .response-content code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }}
        
        .response-content pre {{
            background: #2d2d2d;
            color: #f8f8f2;
            padding: 20px;
            border-radius: 10px;
            overflow-x: auto;
            margin: 20px 0;
        }}
        
        .response-content ul, 
        .response-content ol {{
            margin-left: 20px;
            margin-bottom: 15px;
        }}
        
        .response-content li {{
            margin-bottom: 5px;
        }}
        
        .footer {{
            background: #f8f9fa;
            padding: 30px;
            text-align: center;
            border-top: 1px solid #eee;
        }}
        
        .footer a {{
            color: #667eea;
            text-decoration: none;
        }}
        
        .footer a:hover {{
            text-decoration: underline;
        }}
        
        @media (max-width: 768px) {{
            .header {{
                padding: 30px 20px;
            }}
            
            .content {{
                padding: 20px;
            }}
            
            .info-bar {{
                flex-direction: column;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>GeminiDuck Bot</h1>
            <p class="subtitle">AI-powered assistant with Gemini 3.0</p>
        </div>
        
        <div class="content">
            <div class="info-bar">
                <div class="info-item">
                    <div class="info-label">Дата и время</div>
                    <div>{timestamp}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">ID пользователя</div>
                    <div>{user_id}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Формат</div>
                    <div>HTML документ</div>
                </div>
            </div>
            
            {f'''
            <div class="question-box">
                <h3>Вопрос:</h3>
                <p>{html.escape(query[:500])}</p>
            </div>
            ''' if query else ''}
            
            <div class="response-content">
                {html_content}
            </div>
        </div>
        
        <div class="footer">
            <p>Создано с помощью <a href="https://t.me/geminiduck_bot">GeminiDuck Bot</a> • {timestamp}</p>
            <p>Для новых запросов перейдите в Telegram: @geminiduck_bot</p>
        </div>
    </div>
</body>
</html>"""

# ------------------------- #
#    ОБРАБОТЧИК ОТВЕТОВ    #
# ------------------------- #

class ResponseHandler:
    """Класс для обработки и отправки ответов"""
    
    def __init__(self):
        self.file_manager = FileManager()
    
    async def process_response(self, 
                             update: Update, 
                             context: ContextTypes.DEFAULT_TYPE,
                             response_text: str,
                             original_query: str = "") -> None:
        """Основной метод обработки и отправки ответа"""
        user_id = update.effective_user.id
        
        # Сохраняем ответ
        context.user_data["last_response"] = response_text
        context.user_data["last_query"] = original_query
        
        # Сохраняем в историю
        self._save_to_history(user_id, original_query, response_text)
        
        # Определяем способ отправки
        if len(response_text) <= MAX_TEXT_RESPONSE and '\n' in response_text:
            # Средний ответ - отправляем частями
            await self._send_text_chunks(update, context, response_text)
        elif len(response_text) <= 1000:
            # Короткий ответ - отправляем текстом
            safe_text = self._prepare_text(response_text)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=safe_text,
                parse_mode='Markdown'
            )
        else:
            # Длинный ответ - предлагаем выбор формата
            await self._offer_format_choice(update, context)
    
    def _save_to_history(self, user_id: int, query: str, response: str):
        """Сохраняет запрос и ответ в историю"""
        try:
            history_dir = self.file_manager.get_user_history_dir(user_id)
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            history_file = history_dir / f"session_{timestamp}.txt"
            
            with open(history_file, 'w', encoding='utf-8') as f:
                f.write(f"Вопрос ({timestamp}):\n{query}\n\n")
                f.write(f"Ответ:\n{response}\n")
                f.write("-" * 50 + "\n")
        except Exception as e:
            logger.error(f"Ошибка сохранения истории: {e}")
    
    def _prepare_text(self, text: str) -> str:
        """Подготавливает текст для отправки в Telegram"""
        # Экранируем специальные символы Markdown
        text = text.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
        return text
    
    async def _send_text_chunks(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Отправляет текст частями"""
        chat_id = update.effective_chat.id
        
        # Разбиваем текст на части по 1000 символов
        parts = [text[i:i+1000] for i in range(0, len(text), 1000)]
        
        for i, part in enumerate(parts[:5]):  # Максимум 5 частей
            safe_part = self._prepare_text(part)
            await context.bot.send_message(
                chat_id=chat_id,
                text=safe_part,
                parse_mode='Markdown'
            )
            
            if i < len(parts[:5]) - 1:
                await asyncio.sleep(0.5)
    
    async def _offer_format_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Предлагает выбор формата для длинного ответа"""
        keyboard = [
            [
                InlineKeyboardButton("📄 HTML-документ", callback_data="format_html"),
                InlineKeyboardButton("📊 PDF-документ", callback_data="format_pdf")
            ],
            [
                InlineKeyboardButton("🗑️ Очистить историю", callback_data="clear_history")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ **Ответ готов!**\n\n"
                 f"Длина ответа: {len(context.user_data['last_response'])} символов\n"
                 f"История сохранена в файл\n\n"
                 f"**Выберите формат для просмотра:**\n"
                 f"• HTML-документ — красивое оформление в браузере\n"
                 f"• PDF-документ — удобно для печати и сохранения\n\n"
                 f"_Автоматическая очистка временных файлов каждые 24 часа_",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def send_file_response(self,
                               update: Update,
                               context: ContextTypes.DEFAULT_TYPE,
                               format_type: str) -> None:
        """Отправляет ответ в виде файла выбранного формата"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        chat = query.message.chat
        
        response_text = context.user_data.get("last_response", "")
        original_query = context.user_data.get("last_query", "")
        
        if not response_text:
            await context.bot.send_message(
                chat_id=chat.id,
                text="❌ Ошибка: ответ не найден. Задайте вопрос снова."
            )
            return
        
        # Отправляем сообщение о создании файла
        creating_msg = await context.bot.send_message(
            chat_id=chat.id,
            text=f"🔄 Создаю {format_type.upper()}-документ..."
        )
        
        try:
            if format_type == "html":
                filepath = HTMLGenerator.create_html_from_markdown(
                    response_text, user_id, original_query
                )
                filename = f"ответ_geminiduck_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.html"
                caption = "📄 HTML-версия ответа GeminiDuck"
            else:  # pdf
                filepath = PDFGenerator.create_pdf_from_markdown(
                    response_text, user_id, original_query
                )
                filename = f"ответ_geminiduck_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                caption = "📊 PDF-версия ответа GeminiDuck"
            
            if filepath and filepath.exists():
                with open(filepath, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=chat.id,
                        document=f,
                        filename=filename,
                        caption=caption
                    )
                
                # Удаляем сообщение о создании
                await context.bot.delete_message(
                    chat_id=chat.id,
                    message_id=creating_msg.message_id
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=chat.id,
                    message_id=creating_msg.message_id,
                    text="❌ Не удалось создать документ. Попробуйте другой формат."
                )
                
        except Exception as e:
            logger.error(f"Ошибка отправки файла: {e}")
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=creating_msg.message_id,
                text=f"❌ Ошибка: {str(e)[:100]}"
            )

# ------------------------- #
#       ОСНОВНОЙ КЛАСС     #
# ------------------------- #

class GeminiTelegramBot:
    def __init__(self):
        if not TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN не найден в .env!")
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY не найден в .env!")

        # Настройка Gemini с приоритетом 3.0
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = None
        self.model_name = "Не определена"
        
        # Приоритет моделей
        model_priority = [
            'models/gemini-3.0-flash-latest',
            'models/gemini-3.0-flash',
            'models/gemini-3.0-pro-latest',
            'models/gemini-3.0-pro',
            'models/gemini-2.5-flash',
            'models/gemini-2.5-pro',
            'models/gemini-2.0-flash',
            'models/gemini-1.5-pro-latest',
            'models/gemini-1.0-pro-latest'
        ]
        
        for model_name in model_priority:
            try:
                logger.info(f"Пробуем модель: {model_name}")
                m = genai.GenerativeModel(model_name)
                # Простой тестовый запрос
                response = m.generate_content("Привет!", safety_settings={
                    'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                    'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                    'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                    'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'
                })
                if response.text:
                    self.model = m
                    self.model_name = model_name
                    logger.info(f"✅ Используется модель {model_name}")
                    break
            except Exception as e:
                logger.warning(f"Модель {model_name} недоступна: {str(e)[:100]}")
                continue

        if not self.model:
            raise ValueError("Не удалось инициализировать ни одну модель Gemini.")

        # Инициализация компонентов
        self.file_manager = FileManager()
        self.response_handler = ResponseHandler()
        
        # Telegram-приложение
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.application.bot_data.setdefault("registered_users", set())
        self.application.bot_data.setdefault("warned_users", {})
        
        # Настройка хендлеров
        self.setup_handlers()
        
        # Планировщик задач
        self.setup_scheduler()
        
        logger.info(f"Gemini Telegram Bot готов (модель: {self.model_name})")

    # ------------------------- #
    #    НАСТРОЙКА ХЕНДЛЕРОВ   #
    # ------------------------- #

    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("clear", self.clear_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("history", self.history_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_error_handler(self.error_handler)

    # ------------------------- #
    #     ПЛАНИРОВЩИК ЗАДАЧ    #
    # ------------------------- #

    def setup_scheduler(self):
        """Настройка периодических задач"""
        # Ежедневная очистка в 04:00 по MSK
        self.application.job_queue.run_daily(
            self.daily_cleanup,
            time=datetime.time(hour=4, minute=0, tzinfo=MSK_TZ),
            name="daily_cleanup"
        )
        
        # Очистка временных файлов каждые 3 часа
        self.application.job_queue.run_repeating(
            self.cleanup_temp_files,
            interval=10800,  # 3 часа
            first=10,
            name="temp_files_cleanup"
        )
        
        logger.info("Планировщик задач инициализирован")

    async def daily_cleanup(self, context: ContextTypes.DEFAULT_TYPE):
        """Ежедневная очистка истории и временных файлов"""
        try:
            # Очищаем историю диалогов
            chats_before = len(context.application.chat_data)
            users_before = len(context.application.user_data)
            
            context.application.chat_data.clear()
            context.application.user_data.clear()
            
            # Очищаем временные файлы всех пользователей
            self.file_manager.cleanup_all_old_files(max_age_hours=24)
            
            logger.info(f"🧹 Ежедневная очистка: "
                       f"история ({chats_before} чатов, {users_before} пользователей), "
                       f"временные файлы удалены")
            
            # Отправляем статистику в лог
            total_users = len(context.bot_data.get("registered_users", set()))
            logger.info(f"📊 Статистика: {total_users} зарегистрированных пользователей")
                       
        except Exception as e:
            logger.error(f"Ошибка при ежедневной очистке: {e}")

    async def cleanup_temp_files(self, context: ContextTypes.DEFAULT_TYPE):
        """Очистка временных файлов"""
        try:
            self.file_manager.cleanup_all_old_files(max_age_hours=3)
        except Exception as e:
            logger.error(f"Ошибка очистки временных файлов: {e}")

    # ------------------------- #
    #     ОБРАБОТЧИКИ КОМАНД   #
    # ------------------------- #

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.chat.type != "private":
            await update.message.reply_text(
                "Пожалуйста, напиши мне в личные сообщения /start, чтобы зарегистрироваться 🤝"
            )
            return
        
        user_id = update.effective_user.id
        registered = context.bot_data.setdefault("registered_users", set())
        
        if user_id not in registered:
            registered.add(user_id)
            logger.info(f"✅ Зарегистрирован новый пользователь: {user_id}")
        
        # Очищаем предупреждения
        warned = context.bot_data.setdefault("warned_users", {})
        warned.pop(user_id, None)
        
        # Создаем директории пользователя
        self.file_manager.get_user_base_dir(user_id)
        
        await update.message.reply_text(
            f"👋 Привет, {update.effective_user.first_name}!\n\n"
            f"Я — **GeminiDuck Bot** 🦆, твой AI-помощник.\n\n"
            f"**✨ Особенности:**\n"
            f"• Поддержка Gemini 3.0/2.5/2.0\n"
            f"• Экспорт ответов в HTML и PDF\n"
            f"• Автоматическое сохранение истории\n"
            f"• Ежедневная очистка кэша\n"
            f"• Экономное использование ресурсов\n\n"
            f"**📂 Файловая система:**\n"
            f"• Ваши файлы хранятся в `/tmp/geminiduck/user_{user_id}/`\n"
            f"• История сохраняется на 7 дней\n"
            f"• Временные файлы удаляются автоматически\n\n"
            f"**🔧 Команды:**\n"
            f"/help — справка\n"
            f"/clear — очистить историю\n"
            f"/status — информация о боте\n"
            f"/history — управление историей\n\n"
            f"Задавайте вопросы — я помогу! 💡",
            parse_mode='Markdown'
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = (
            "**🦆 Помощь по GeminiDuck Bot**\n\n"
            "**Основные команды:**\n"
            "• /start — регистрация и информация\n"
            "• /help — эта справка\n"
            "• /clear — очистить историю диалога\n"
            "• /status — статус бота и модель\n"
            "• /history — управление историей запросов\n\n"
            "**Как работает бот:**\n"
            "1. Задаете вопрос\n"
            "2. Если ответ короткий (<500 симв.) — получаете текст\n"
            "3. Если ответ длинный — выбираете формат (HTML/PDF)\n"
            "4. Ответ сохраняется в вашу историю\n"
            "5. История автоматически очищается каждые 7 дней\n\n"
            "**Файловая система:**\n"
            "• Ваши файлы: `/tmp/geminiduck/user_ВАШ_ID/`\n"
            "• История: history/ (хранится 7 дней)\n"
            "• Временные файлы: temp/ (очищаются каждые 24 часа)\n\n"
            "**Техническая информация:**\n"
            f"• Используемая модель: {self.model_name}\n"
            f"• Сервер: 194.48.142.129\n"
            f"• Максимальная длина ответа: {MAX_TOTAL_CHARS} символов"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Очищаем историю диалога
        context.chat_data.clear()
        context.user_data.clear()
        
        # Очищаем файлы пользователя
        self.file_manager.cleanup_user_files(user_id)
        
        await update.message.reply_text(
            "🧹 **История полностью очищена!**\n\n"
            "• Удалена история диалога\n"
            "• Удалены временные файлы\n"
            "• Директория пользователя очищена\n"
            "• Начинаем новый диалог\n\n"
            "Задавайте новый вопрос 👇",
            parse_mode='Markdown'
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Считаем статистику
        registered_users = len(context.bot_data.get("registered_users", set()))
        active_chats = len(context.application.chat_data)
        
        status_text = (
            f"**🟢 GeminiDuck Bot активен**\n\n"
            f"**Модель:** {self.model_name}\n"
            f"**Пользователей:** {registered_users}\n"
            f"**Активных чатов:** {active_chats}\n"
            f"**Текстовый лимит:** {MAX_TEXT_RESPONSE} символов\n"
            f"**Общий лимит:** {MAX_TOTAL_CHARS} символов\n\n"
            f"**Статус системы:**\n"
            f"• Сервер: 194.48.142.129 ✅\n"
            f"• Файловая система: /tmp/geminiduck/ ✅\n"
            f"• Автоочистка: ✅ Включена\n"
            f"• Экспорт HTML/PDF: ✅ Доступен\n"
            f"• Сохранение истории: ✅ Включено\n\n"
            f"**Расписание очистки:**\n"
            f"• Временные файлы: каждые 3 часа\n"
            f"• История диалогов: ежедневно в 04:00 МСК\n"
            f"• Файлы истории: через 7 дней"
        )
        await update.message.reply_text(status_text, parse_mode='Markdown')

    async def history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает информацию о истории запросов"""
        user_id = update.effective_user.id
        history_dir = self.file_manager.get_user_history_dir(user_id)
        
        if history_dir.exists():
            history_files = list(history_dir.glob("*.txt"))
            
            if history_files:
                # Сортируем по дате создания (новые первыми)
                history_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                
                total_size = sum(f.stat().st_size for f in history_files[:10])
                latest_files = history_files[:5]  # Показываем 5 последних
                
                history_info = (
                    f"📚 **Ваша история запросов**\n\n"
                    f"• Всего файлов: {len(history_files)}\n"
                    f"• Последние 5 файлов:\n"
                )
                
                for i, file_path in enumerate(latest_files, 1):
                    file_time = datetime.datetime.fromtimestamp(file_path.stat().st_mtime)
                    file_size = file_path.stat().st_size
                    history_info += f"{i}. {file_time.strftime('%d.%m %H:%M')} ({file_size} байт)\n"
                
                history_info += f"\nОбщий размер: {total_size} байт"
                history_info += "\n\nДля очистки используйте /clear"
                
            else:
                history_info = "📭 История запросов пуста."
        else:
            history_info = "📭 История запросов не найдена."
        
        await update.message.reply_text(history_info, parse_mode='Markdown')

    # ------------------------- #
    #     GEMINI API           #
    # ------------------------- #

    def get_gemini_response(self, message: str, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Получение ответа от Gemini API с Markdown форматированием"""
        try:
            # Получаем историю диалога
            history = context.chat_data.get("conversation", [])
            
            # Формируем промпт с инструкцией по Markdown
            prompt_parts = [
                "Ты - полезный AI-ассистент GeminiDuck.",
                "Отвечай подробно и информативно.",
                "Используй Markdown форматирование для улучшения читаемости:",
                "1. Заголовки: # Заголовок 1, ## Заголовок 2",
                "2. Жирный текст: **жирный**",
                "3. Курсив: *курсив*",
                "4. Списки: - пункт или 1. пункт",
                "5. Код: `встроенный код` или ```многострочный код```",
                "6. Цитаты: > цитата",
                "7. Горизонтальные линии: ---",
                "Разделяй ответ на логические части с помощью заголовков.",
                "Будь точным и информативным.\n\n"
            ]
            
            # Добавляем историю (последние 3 обмена)
            for msg in history[-6:]:
                role = "Пользователь" if msg["role"] == "user" else "Ассистент"
                prompt_parts.append(f"{role}: {msg['content']}")
            
            prompt_parts.append(f"Пользователь: {message}")
            prompt_parts.append("Ассистент:")
            
            prompt = "\n".join(prompt_parts)
            
            # Генерируем ответ
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=4000,
                    temperature=0.7,
                    top_p=0.9
                ),
                safety_settings={
                    'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                    'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                    'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                    'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'
                }
            )
            
            text = response.text.strip()
            
            # Обрезаем если превышен лимит
            if len(text) > MAX_TOTAL_CHARS:
                text = text[:MAX_TOTAL_CHARS] + "\n\n[Ответ обрезан из-за ограничения длины]"
            
            # Сохраняем в историю
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": text})
            
            # Ограничиваем размер истории
            context.chat_data["conversation"] = history[-10:]
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка Gemini API: {e}")
            return f"❌ **Ошибка при обращении к AI:**\n\n```{str(e)[:200]}```\n\nПожалуйста, попробуйте еще раз."

    # ------------------------- #
    #  CALLBACK QUERY HANDLER   #
    # ------------------------- #

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        data = query.data
        
        if data.startswith("format_"):
            format_type = data.replace("format_", "")
            await self.response_handler.send_file_response(update, context, format_type)
            
        elif data == "clear_history":
            await query.answer()
            user_id = update.effective_user.id
            
            # Очищаем историю
            context.chat_data.clear()
            context.user_data.clear()
            self.file_manager.cleanup_user_files(user_id)
            
            await query.edit_message_text(
                text="🧹 **История очищена!**\n\n"
                     "Все временные файлы удалены.\n"
                     "Директория пользователя очищена.\n"
                     "Можете задавать новый вопрос.",
                parse_mode='Markdown'
            )

    # ------------------------- #
    #     ГЛАВНЫЙ ОБРАБОТЧИК   #
    # ------------------------- #

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg or not msg.text:
            return

        user = update.effective_user
        user_id = user.id
        chat = msg.chat
        chat_type = chat.type
        text = msg.text.strip()
        lower_text = text.lower()

        logger.info(f"Сообщение от {user_id} в {chat_type}: {text[:100]}")

        registered = context.bot_data.setdefault("registered_users", set())
        warned = context.bot_data.setdefault("warned_users", {})

        # Поведение в группе
        if chat_type in ("group", "supergroup"):
            if not (f"@{BOT_USERNAME}" in lower_text or lower_text.startswith(BOT_ALIAS)):
                return

            if user_id not in registered:
                count = warned.get(user_id, 0)
                if count == 0:
                    await msg.reply_text(
                        f"{user.first_name}, для взаимодействия со мной отправь мне личное сообщение с командой /start 🤝"
                    )
                    warned[user_id] = 1
                return

            clean_text = re.sub(rf"@{BOT_USERNAME}\b", "", text, flags=re.IGNORECASE)
            clean_text = re.sub(rf"{BOT_ALIAS}\b", "", clean_text, flags=re.IGNORECASE).strip()
            if not clean_text:
                await msg.reply_text("Я слушаю 👂, но ты ничего не спросил.")
                return
            text = clean_text

        try:
            # Показываем статус "печатает"
            await msg.chat.send_action("typing")
            
            # Получаем ответ от Gemini
            response_text = self.get_gemini_response(text, context)
            
            # Обрабатываем и отправляем ответ
            await self.response_handler.process_response(update, context, response_text, text)
            
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            await msg.reply_text(
                "❌ **Произошла ошибка при обработке запроса.**\n\n"
                "Пожалуйста, попробуйте еще раз или используйте /clear для очистки истории.",
                parse_mode='Markdown'
            )

    # ------------------------- #
    #     ОБРАБОТЧИК ОШИБОК    #
    # ------------------------- #

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Ошибка: {context.error}", exc_info=context.error)
        if update and getattr(update, "message", None):
            try:
                await update.message.reply_text(
                    "⚠️ **Внутренняя ошибка бота.**\n\n"
                    "Попробуйте позже или используйте /clear для очистки истории.",
                    parse_mode='Markdown'
                )
            except Exception:
                pass

    # ------------------------- #
    #         ЗАПУСК            #
    # ------------------------- #

    def run(self):
        logger.info("Бот запущен и слушает обновления...")
        logger.info(f"Сервер: 194.48.142.129")
        logger.info(f"Используемая модель: {self.model_name}")
        logger.info(f"Базовая директория файлов: {self.file_manager.base_dir}")
        self.application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

# ------------------------- #
#        ТОЧКА ВХОДА        #
# ------------------------- #

def main():
    try:
        bot = GeminiTelegramBot()
        bot.run()
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
from random import choice
from time import time
from copy import deepcopy
from pytz import timezone
from datetime import datetime
from urllib.parse import unquote, quote
from requests import utils as rutils
from aiofiles.os import path as aiopath, remove as aioremove, listdir, makedirs
from os import walk, path as ospath
from html import escape
from aioshutil import move
from asyncio import create_subprocess_exec, sleep, Event
from pyrogram.enums import ChatType

from bot import OWNER_ID, Interval, aria2, DOWNLOAD_DIR, download_dict, download_dict_lock, LOGGER, bot_name, DATABASE_URL, \
    MAX_SPLIT_SIZE, config_dict, status_reply_dict_lock, user_data, non_queued_up, non_queued_dl, queued_up, \
    queued_dl, queue_dict_lock, bot, GLOBAL_EXTENSION_FILTER
from bot.helper.ext_utils.bot_utils import extra_btns, sync_to_async, get_readable_file_size, get_readable_time, is_mega_link, is_gdrive_link
from bot.helper.ext_utils.fs_utils import get_base_name, get_path_size, clean_download, clean_target, \
    is_first_archive_split, is_archive, is_archive_split, join_files
from bot.helper.ext_utils.leech_utils import split_file, format_filename
from bot.helper.ext_utils.exceptions import NotSupportedExtractionArchive
from bot.helper.ext_utils.task_manager import start_from_queued
from bot.helper.mirror_utils.status_utils.extract_status import ExtractStatus
from bot.helper.mirror_utils.status_utils.zip_status import ZipStatus
from bot.helper.mirror_utils.status_utils.split_status import SplitStatus
from bot.helper.mirror_utils.status_utils.gdrive_status import GdriveStatus
from bot.helper.mirror_utils.status_utils.telegram_status import TelegramStatus
from bot.helper.mirror_utils.status_utils.ddl_status import DDLStatus
from bot.helper.mirror_utils.status_utils.rclone_status import RcloneStatus
from bot.helper.mirror_utils.status_utils.queue_status import QueueStatus
from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.mirror_utils.upload_utils.pyrogramEngine import TgUploader
from bot.helper.mirror_utils.upload_utils.ddlEngine import DDLUploader
from bot.helper.mirror_utils.rclone_utils.transfer import RcloneTransferHelper
from bot.helper.telegram_helper.message_utils import sendCustomMsg, sendMessage, editMessage, deleteMessage, delete_all_messages, delete_links, sendMultiMessage, update_all_messages
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.ext_utils.db_handler import DbManger
from bot.helper.ext_utils.weekly_leech_banter import maybe_send_weekly_leech_banter
from bot.helper.themes import BotTheme


class MirrorLeechListener:
    def __init__(self, message, compress=False, extract=False, isQbit=False, isLeech=False, tag=None, select=False, seed=False, sameDir=None, rcFlags=None, upPath=None, isClone=False, 
                join=False, drive_id=None, index_link=None, isYtdlp=False, source_url=None, logMessage=None, leech_utils={}):
        if sameDir is None:
            sameDir = {}
        self.message = message
        self.uid = message.id
        self.excep_chat = bool(str(message.chat.id) in config_dict['EXCEP_CHATS'].split())
        self.extract = extract
        self.compress = compress
        self.isQbit = isQbit
        self.isLeech = isLeech
        self.isClone = isClone
        self.isMega = is_mega_link(source_url) if source_url else False
        self.isGdrive = is_gdrive_link(source_url) if source_url else False
        self.isYtdlp = isYtdlp
        self.tag = tag
        self.seed = seed
        self.newDir = ""
        self.dir = f"{DOWNLOAD_DIR}{self.uid}"
        self.select = select
        self.isSuperGroup = message.chat.type in [ChatType.SUPERGROUP, ChatType.CHANNEL]
        self.isPrivate = message.chat.type == ChatType.BOT
        self.user_id = self.message.from_user.id
        self.user_dict = user_data.get(self.user_id, {})
        self.isPM = config_dict['BOT_PM'] or self.user_dict.get('bot_pm')
        self.suproc = None
        self.sameDir = sameDir
        self.rcFlags = rcFlags
        self.upPath = upPath
        self.random_pic = 'IMAGES' if config_dict['IMAGES'] else None
        self.join = join
        self.drive_id = drive_id
        self.index_link = index_link
        self.logMessage = logMessage
        self.linkslogmsg = None
        self.botpmmsg = None
        self.upload_details = {}
        self.leech_utils = leech_utils
        self.source_url = (
            source_url
            if source_url and source_url.startswith('http')
            else f"https://t.me/share/url?url={source_url}"
            if source_url
            else message.link
        )
        self.source_msg = ''
        self.__setModeEng()
        self.__parseSource()

    async def clean(self):
        try:
            async with status_reply_dict_lock:
                if Interval:
                    Interval[0].cancel()
                    Interval.clear()
            await sync_to_async(aria2.purge)
            await delete_all_messages()
        except Exception:
            pass

    def __setModeEng(self):
        mode = f" #{'Leech' if self.isLeech else 'Clone' if self.isClone else 'RClone' if self.upPath not in ['gd', 'ddl'] else 'DDL' if self.upPath != 'gd' else 'GDrive'}"
        mode += ' (Zip)' if self.compress else ' (Unzip)' if self.extract else ''
        mode += f" | #{'qBit' if self.isQbit else 'ytdlp' if self.isYtdlp else 'GDrive' if (self.isClone or self.isGdrive) else 'Mega' if self.isMega else 'Aria2' if self.source_url and self.source_url != self.message.link else 'Tg'}"
        self.upload_details['mode'] = mode
        
    def __parseSource(self):
        if self.source_url == self.message.link:
            file = self.message.reply_to_message
            if file:
                self.source_url = file.link
            if file is not None and file.media is not None:
                mtype = file.media.value
                media = getattr(file, mtype)
                self.source_msg = f'â” <b>Name:</b> <i>{media.file_name if hasattr(media, "file_name") else f"{mtype}_{media.file_unique_id}"}</i>\nâ”  <b>Type:</b> {media.mime_type if hasattr(media, "mime_type") else "image/jpeg" if mtype == "photo" else "text/plain"}\nâ”  <b>Size:</b> {get_readable_file_size(media.file_size)}\nâ”  <b>Created Date:</b> {media.date}\nâ”– <b>Media Type:</b> {mtype.capitalize()}'
            else:
                self.source_msg = f"<code>{self.message.reply_to_message.text}</code>"
        elif self.source_url.startswith('https://t.me/share/url?url='):
            msg = self.source_url.replace('https://t.me/share/url?url=', '')
            if msg.startswith('magnet'):
                mag = unquote(msg).split('&')
                tracCount, name, amper = 0, '', False
                for check in mag:
                    if check.startswith('tr='):
                        tracCount += 1
                    elif check.startswith('magnet:?xt=urn:btih:'):
                        hashh = check.replace('magnet:?xt=urn:btih:', '')
                    else:
                        name += ('&' if amper else '') + check.replace('dn=', '').replace('+', ' ')
                        amper = True
                self.source_msg = f"â” <b>Name:</b> <i>{name}</i>\nâ”  <b>Magnet Hash:</b> <code>{hashh}</code>\nâ”  <b>Total Trackers:</b> {tracCount} \nâ”– <b>Share:</b> <a href='https://t.me/share/url?url={quote(msg)}'>Share To Telegram</a>"
            else:
                self.source_msg = f"<code>{msg}</code>"
        else:
            self.source_msg = f"<code>{self.source_url}</code>"
        
    async def onDownloadStart(self):
        if config_dict['LINKS_LOG_ID'] and not self.excep_chat:
            dispTime = datetime.now(timezone(config_dict['TIMEZONE'])).strftime('%d/%m/%y, %I:%M:%S %p')
            self.linkslogmsg = await sendCustomMsg(config_dict['LINKS_LOG_ID'], BotTheme('LINKS_START', Mode=self.upload_details['mode'], Tag=self.tag) + BotTheme('LINKS_SOURCE', On=dispTime, Source=self.source_msg))
        if self.isPM and self.isSuperGroup:
            self.botpmmsg = await sendCustomMsg(self.message.from_user.id, BotTheme('PM_START', msg_link=self.source_url))
        if self.isSuperGroup and config_dict['INCOMPLETE_TASK_NOTIFIER'] and DATABASE_URL:
            await DbManger().add_incomplete_task(self.message.chat.id, self.message.link, self.tag, self.source_url, self.message.text)

    async def onDownloadComplete(self):
        multi_links = False
        while True:
            if self.sameDir:
                if self.sameDir['total'] in [1, 0] or self.sameDir['total'] > 1 and len(self.sameDir['tasks']) > 1:
                    break
            else:
                break
            await sleep(0.2)
        async with download_dict_lock:
            if self.sameDir and self.sameDir['total'] > 1:
                self.sameDir['tasks'].remove(self.uid)
                self.sameDir['total'] -= 1
                folder_name = self.sameDir['name']
                spath = f"{self.dir}/{folder_name}"
                des_path = f"{DOWNLOAD_DIR}{list(self.sameDir['tasks'])[0]}/{folder_name}"
                await makedirs(des_path, exist_ok=True)
                for item in await listdir(spath):
                    if item.endswith(('.aria2', '.!qB')):
                        continue
                    item_path = f"{self.dir}/{folder_name}/{item}"
                    if item in await listdir(des_path):
                        await move(item_path, f'{des_path}/{self.uid}-{item}')
                    else:
                        await move(item_path, f'{des_path}/{item}')
                multi_links = True
            download = download_dict[self.uid]
            name = str(download.name()).replace('/', '')
            gid = download.gid()
        LOGGER.info(f"Download Completed: {name}")
        if multi_links:
            await self.onUploadError('Downloaded! Starting other part of the Task...')
            return
        if name == "None" or self.isQbit or not await aiopath.exists(f"{self.dir}/{name}"):
            try:
                files = await listdir(self.dir)
            except Exception as e:
                await self.onUploadError(str(e))
                return
            name = files[-1]
            if name == "yt-dlp-thumb":
                name = files[0]

        dl_path = f"{self.dir}/{name}"
        up_path = ''
        size = await get_path_size(dl_path)
        async with queue_dict_lock:
            if self.uid in non_queued_dl:
                non_queued_dl.remove(self.uid)
        await start_from_queued()
        user_dict = user_data.get(self.message.from_user.id, {})
        
        if self.join and await aiopath.isdir(dl_path):
            await join_files(dl_path)

        if self.extract:
            pswd = self.extract if isinstance(self.extract, str) else ''
            try:
                if await aiopath.isfile(dl_path):
                    up_path = get_base_name(dl_path)
                LOGGER.info(f"Extracting: {name}")
                async with download_dict_lock:
                    download_dict[self.uid] = ExtractStatus(
                        name, size, gid, self)
                if await aiopath.isdir(dl_path):
                    if self.seed:
                        self.newDir = f"{self.dir}10000"
                        up_path = f"{self.newDir}/{name}"
                    else:
                        up_path = dl_path
                    for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                        for file_ in files:
                            if is_first_archive_split(file_) or is_archive(file_) and not file_.endswith('.rar'):
                                f_path = ospath.join(dirpath, file_)
                                t_path = dirpath.replace(
                                    self.dir, self.newDir) if self.seed else dirpath
                                cmd = [
                                    "7z", "x", f"-p{pswd}", f_path, f"-o{t_path}", "-aot", "-xr!@PaxHeader"]
                                if not pswd:
                                    del cmd[2]
                                if self.suproc == 'cancelled' or self.suproc is not None and self.suproc.returncode == -9:
                                    return
                                self.suproc = await create_subprocess_exec(*cmd)
                                code = await self.suproc.wait()
                                if code == -9:
                                    return
                                elif code != 0:
                                    LOGGER.error(
                                        'Unable to extract archive splits!')
                        if not self.seed and self.suproc is not None and self.suproc.returncode == 0:
                            for file_ in files:
                                if is_archive_split(file_) or is_archive(file_):
                                    del_path = ospath.join(dirpath, file_)
                                    try:
                                        await aioremove(del_path)
                                    except:
                                        return
                else:
                    if self.seed:
                        self.newDir = f"{self.dir}10000"
                        up_path = up_path.replace(self.dir, self.newDir)
                    cmd = ["7z", "x", f"-p{pswd}", dl_path,
                           f"-o{up_path}", "-aot", "-xr!@PaxHeader"]
                    if not pswd:
                        del cmd[2]
                    if self.suproc == 'cancelled':
                        return
                    self.suproc = await create_subprocess_exec(*cmd)
                    code = await self.suproc.wait()
                    if code == -9:
                        return
                    elif code == 0:
                        LOGGER.info(f"Extracted Path: {up_path}")
                        if not self.seed:
                            try:
                                await aioremove(dl_path)
                            except:
                                return
                    else:
                        LOGGER.error(
                            'Unable to extract archive! Uploading anyway')
                        self.newDir = ""
                        up_path = dl_path
            except NotSupportedExtractionArchive:
                LOGGER.info("Not any valid archive, uploading file as it is.")
                self.newDir = ""
                up_path = dl_path

        if self.compress:
            pswd = self.compress if isinstance(self.compress, str) else ''
            if up_path:
                dl_path = up_path
                up_path = f"{up_path}.zip"
            elif self.seed and self.isLeech:
                self.newDir = f"{self.dir}10000"
                up_path×½¹¶‰Ëkºwµç[ØYÜİ]\Âˆ]ØZ]\]WØ[ÛY\ÜØYÙ\Ê
B‚ˆ]ØZ]Ş[˜×İ×Ø\Ş[˜Êš]™K\ØY\Û˜[YKÚ^™KÙ[‹™š]™WÚY
Bˆ[YˆÙ[‹\]OH	Ù	Î‚ˆÚ^™HH]ØZ]Ù]Ü]ÜÚ^™J\Ü]
BˆÑÑÑT‹š[™›Êˆ•\ØY˜[YNˆİ\Û˜[Y_HšXHŠBˆH\ØY\ŠÙ[‹\Û˜[YK\Ù\ŠBˆİ\ØYÜİ]\ÈHİ]\ÊÚ^™KÙ[‹›Y\ÜØYÙKÚYÙ[‹\ØYÙ]Z[ÊBˆ\Ş[˜ÈÚ]İÛ›ØYÙXİÛØÚÎ‚ˆİÛ›ØYÙXİÜÙ[‹ZYHHİ\ØYÜİ]\Âˆ]ØZ]\]WØ[ÛY\ÜØYÙ\Ê
Bˆ]ØZ]\ØY
\Û˜[YKÚ^™JBˆ[ÙN‚ˆÚ^™HH]ØZ]Ù]Ü]ÜÚ^™J\Ü]
BˆÑÑÑT‹š[™›Êˆ•\ØY˜[YNˆİ\Û˜[Y_HšXHÛÛ™HŠBˆÕ˜[œÙ™\ˆH˜ÛÛ™U˜[œÙ™\’[\ŠÙ[‹\Û˜[YJBˆ\Ş[˜ÈÚ]İÛ›ØYÙXİÛØÚÎ‚ˆİÛ›ØYÙXİÜÙ[‹ZYHH˜ÛÛ™Tİ]\ÊˆÕ˜[œÙ™\‹Ù[‹›Y\ÜØYÙKÚY	İ\	ËÙ[‹\ØYÙ]Z[ÊBˆ]ØZ]\]WØ[ÛY\ÜØYÙ\Ê
Bˆ]ØZ]Õ˜[œÙ™\‹\ØY
\Ü]Ú^™JB‚ˆ\Ş[˜ÈYˆÛ•\ØYÛÛ\]JÙ[‹[šËÚ^™Kš[\Ë›Û\œËZ[YWİ\K˜[YK˜ÛÛ™T]IÉËš]˜]OQ˜[ÙJN‚ˆYˆÙ[‹š\Ôİ\\‘Ü›İ\[™ÛÛ™šY×ÙXİÉÒSÓÓTUWÕTÒ×Ó“ÕQ’QT‰×H[™UPTÑWÕT“‚ˆ]ØZ]“X[™Ù\Š
Kœ›WØÛÛ\]Wİ\ÚÊÙ[‹›Y\ÜØYÙK›[šÊBˆ\Ù\—ÚYHÙ[‹›Y\ÜØYÙK™œ›ÛWİ\Ù\‹šYˆ˜[YKÈH]ØZ]›Ü›X]Ùš[[˜[YJ˜[YK\Ù\—ÚY\ÓZ\œ›Ü[›İÙ[‹š\ÓYXÚ
Bˆ\Ù\—ÙXİH\Ù\—Ù]K™Ù]
\Ù\—ÚYßJBˆ\ÙÈH›İ[YJ	ÓSQIË˜[YOH•\ÚÈ\È™Y[ˆÛÛ\]YHšYˆÛÛ™šY×ÙXİÉÔĞQ‘WÓSÑI×H[™Ù[‹š\Ôİ\\‘Ü›İ\[ÙH\ØØ\J˜[YJJBˆ\ÙÈ
ÏH›İ[YJ	ÔÒV‘IËÚ^™OYÙ]Ü™XYX›WÙš[WÜÚ^™JÚ^™JJBˆ\ÙÈ
ÏH›İ[YJ	ÑSTÑIË[YOYÙ]Ü™XYX›Wİ[YJ[YJ
HHÙ[‹›Y\ÜØYÙK™]K[Y\İ[\

JJBˆ\ÙÈ
ÏH›İ[YJ	ÓSÑIË[ÙO\Ù[‹\ØYÙ]Z[ÖÉÛ[ÙI×JBˆÑÑÑT‹š[™›Ê‰Õ\ÚÈÛ™NˆÛ˜[Y_IÊBˆˆ]ÛœÈH]Û“XZÙ\Š
BˆYˆÙ[‹š\ÓYXÚ‚ˆ\ÙÈ
ÏH›İ[YJ	ÓÕÕSÑ’STÉËš[\ÏY›Û\œÊBˆYˆZ[YWİ\HOH‚ˆ\ÙÈ
ÏH›İ[YJ	ÓĞÓÔ”•TQÑ’STÉËÛÜœ\[Z[YWİ\JBˆ\ÙÈ
ÏH›İ[YJ	ÓĞĞÉËYÏ\Ù[‹YÊBˆ—ØYYH˜[ÙB‚ˆYˆ›İš[\Î‚ˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹›Y\ÜØYÙK\ÙËİÏ\Ù[‹œ˜[™ÛWÜXÊBˆ[ÙN‚ˆˆH]Û“XZÙ\Š
BˆØ]™YH˜[ÙBˆYˆÙ[‹œÛİ\˜ÙWİ\›[™ÛÛ™šY×ÙXİÉÔÓÕTÑWÓS’É×N‚ˆ‹X]ÛŠ›İ[YJ	ÔÓÕTÑWÕT“	ÊKÙ[‹œÛİ\˜ÙWİ\›
BˆYˆÙ[‹š\Ôİ\\‘Ü›İ\‚ˆˆH^˜WØœÊŠVÌBˆY\ÜØYÙHH\ÙÂˆœÈH‹˜Z[ÛY[JŠBˆ]ÛœÈH‚ˆYˆÙ[‹š\Ôİ\\‘Ü›İ\[™›İÙ[‹š\ÔN‚ˆY\ÜØYÙH
ÏH›İ[YJ	ÓÓÓTÑÉÊBˆ[YˆÙ[‹š\Ôİ\\‘Ü›İ\[™Ù[‹š\ÔN‚ˆY\ÜØYÙH
ÏH›İ[YJ	ÓÓÓTÑÉÊBˆY\ÜØYÙH
ÏH›İ[YJ	ÓĞ“ÕÓTÑÉÊBˆ]ÛœËšX]ÛŠ›İ[YJ	ĞÒPÒ×ÔIÊKˆŞ›[İ\Ù\—ÚYH›İH‹	ÚXY\‰ÊBˆYˆÛÛ™šY×ÙXİÉÔĞQ‘WÓSÑI×H[™Ù[‹š\Ôİ\\‘Ü›İ\‚ˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹›Y\ÜØYÙKY\ÜØYÙK]ÛœË˜Z[ÛY[JŠKİÏ\Ù[‹œ˜[™ÛWÜXÊBˆ›\ÙÈH	×‰Âˆ›Üˆ[™^
[šË˜[YJH[ˆ[[Y\˜]Jš[\Ëš][\Ê
Kİ\LJN‚ˆ›\ÙÈ
ÏHˆÚ[™^KˆH™YIŞÛ[šßIÏÛ˜[Y_OØO—ˆ‚ˆYˆ[Š\ÙË™[˜ÛÙJ
H
È›\ÙË™[˜ÛÙJ
JHˆ
Yˆ[ŠÛÛ™šY×ÙXİÉÒSPQÑTÉ×JHOH[ÙHL
N‚ˆˆYˆÛÛ™šY×ÙXİÉÔĞQ‘WÓSÑI×N‚ˆYˆÙ[‹š\Ôİ\\‘Ü›İ\‚ˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹˜›İ[\ÙË\ÙÈ
È›İ[YJ	ÓÓÓTÑÉÊH
È›\ÙËœËİÏ\Ù[‹œ˜[™ÛWÜXÊBˆ[ÙN‚ˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹›Y\ÜØYÙKY\ÜØYÙH
È›\ÙË]ÛœË˜Z[ÛY[JŠKİÏ\Ù[‹œ˜[™ÛWÜXÊBˆ[ÙN‚ˆYˆÛÛ™šY×ÙXİÉÔĞU‘WÓTÑÉ×H[™›İØ]™Y[™Ù[‹š\Ôİ\\‘Ü›İ\‚ˆØ]™YHYBˆ]ÛœËšX]ÛŠ›İ[YJ	ÔĞU‘WÓTÑÉÊK	ÜØ]™IË	Ù›Ûİ\‰ÊBˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹›Y\ÜØYÙKY\ÜØYÙH
È›\ÙË]ÛœË˜Z[ÛY[JŠKİÏ\Ù[‹œ˜[™ÛWÜXÊBˆ]ØZ]ÛY\
KJBˆ›\ÙÈH	ÉÂ‚ˆYˆ›\ÙÈOH	×‰Î‚ˆYˆÛÛ™šY×ÙXİÉÔĞQ‘WÓSÑI×N‚ˆYˆÙ[‹š\Ôİ\\‘Ü›İ\‚ˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹˜›İ[\ÙË\ÙÈ
È›İ[YJ	ÓÓÓTÑÉÊH
È›\ÙËœËİÏ\Ù[‹œ˜[™ÛWÜXÊBˆ[ÙN‚ˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹›Y\ÜØYÙKY\ÜØYÙH
È›\ÙË]ÛœË˜Z[ÛY[JŠKİÏ\Ù[‹œ˜[™ÛWÜXÊBˆ[ÙN‚ˆYˆÛÛ™šY×ÙXİÉÔĞU‘WÓTÑÉ×H[™›İØ]™Y[™Ù[‹š\Ôİ\\‘Ü›İ\‚ˆØ]™YHYBˆ]ÛœËšX]ÛŠ›İ[YJ	ÔĞU‘WÓTÑÉÊK	ÜØ]™IË	Ù›Ûİ\‰ÊBˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹›Y\ÜØYÙKY\ÜØYÙH
È›\ÙË]ÛœË˜Z[ÛY[JŠKİÏ\Ù[‹œ˜[™ÛWÜXÊB‚ˆ]ØZ]X^X™WÜÙ[™İÙYZÛWÛYXÚØ˜[\ŠˆÙ[‹›Y\ÜØYÙK˜Ú]šYÙ[‹›Y\ÜØYÙKšY\Ù\—ÚYÙ[‹YÊBˆˆYˆÙ[‹œÙYY‚ˆYˆÙ[‹›™]Ñ\‚ˆ]ØZ]ÛX[—İ\™Ù]
Ù[‹›™]Ñ\ŠBˆ\Ş[˜ÈÚ]]Y]YWÙXİÛØÚÎ‚ˆYˆÙ[‹ZY[ˆ›Û—Ü]Y]YYİ\‚ˆ›Û—Ü]Y]YYİ\œ™[[İ™JÙ[‹ZY
Bˆ]ØZ]İ\Ùœ›ÛWÜ]Y]YY

Bˆ™]\›‚ˆ[ÙN‚ˆ\ÙÈ
ÏH›İ[YJ	ÓWÕTIËZ[Y]\O[Z[YWİ\JBˆYˆZ[YWİ\HOH‘›Û\ˆ‚ˆ\ÙÈ
ÏH›İ[YJ	ÓWÔÕP‘“Ó	Ë›Û\Y›Û\œÊBˆ\ÙÈ
ÏH›İ[YJ	ÕÕSÑ’STÉËš[\ÏYš[\ÊBˆYˆ[šÈÜˆ˜ÛÛ™T][™ÛÛ™šY×ÙXİÉÔÓÓ‘WÔÑT•‘WÕT“	×H[™›İš]˜]N‚ˆYˆ
\×ÑH\Ú[œİ[˜ÙJ[šËXİ
JN‚ˆ›Üˆ\[šÈ[ˆ[šËš][\Ê
N‚ˆ]ÛœËX]ÛŠ›İ[YJ	ÑÓS’ÉËÙ\Y\
K[šÊBˆ[Yˆ[šÈ[™
\Ù\—ÚYOHÕÓ‘T—ÒQÜˆ›İÛÛ™šY×ÙXİÉÑTĞP“WÑ’U‘WÓS’É×JN‚ˆ]ÛœËX]ÛŠ›İ[YJ	ĞÓÕQÓS’ÉÊK[šÊBˆ[ÙN‚ˆ\ÙÈ
ÏH›İ[YJ	ÔÔU	ËÜ]\˜ÛÛ™T]
BˆYˆ˜ÛÛ™T][™
ÓÓ‘WÔÑT•‘WÕT“HÛÛ™šY×ÙXİÉÔÓÓ‘WÔÑT•‘WÕT“	×JN‚ˆ™[[İK]H˜ÛÛ™T]œÜ]
	Î‰ËJBˆ\›Ü]H][Ëœ][İJ‰ŞÜ]IÊBˆÚ\™Wİ\›H‰ŞÔÓÓ‘WÔÑT•‘WÕT“KŞÜ™[[İ_KŞİ\›Ü]IÂˆYˆZ[YWİ\HOH‘›Û\ˆ‚ˆÚ\™Wİ\›
ÏH	ËÉÂˆ]ÛœËX]ÛŠ›İ[YJ	ÔÓÓ‘WÓS’ÉÊKÚ\™Wİ\›
Bˆ[Yˆ›İ˜ÛÛ™T][™›İ\×Ñ‚ˆS‘VÕT“HÙ[‹š[™^Û[šÈYˆÙ[‹™š]™WÚY[ÙHÛÛ™šY×ÙXİÉÒS‘VÕT“	×BˆYˆS‘VÕT“‚ˆ\›Ü]H][Ëœ][İJ‰ŞÛ˜[Y_IÊBˆÚ\™Wİ\›H‰ŞÒS‘VÕT“KŞİ\›Ü]IÂˆYˆZ[YWİ\HOH‘›Û\ˆ‚ˆÚ\™Wİ\›
ÏH	ËÉÂˆ]ÛœËX]ÛŠ›İ[YJ	ÒS‘VÓS’×Ñ‰ÊKÚ\™Wİ\›
Bˆ[ÙN‚ˆ]ÛœËX]ÛŠ›İ[YJ	ÒS‘VÓS’×Ñ	ÊKÚ\™Wİ\›
BˆYˆZ[YWİ\Kœİ\İÚ]

	Ú[XYÙIË	İšY[ÉË	Ø]Y[ÉÊJN‚ˆÚ\™Wİ\›ÈH‰ŞÒS‘VÕT“KŞİ\›Ü]OØO]šY]ÉÂˆ]ÛœËX]ÛŠ›İ[YJ	Õ’QU×ÓS’ÉÊKÚ\™Wİ\›ÊBˆˆ[ÙN‚ˆ\ÙÈ
ÏH›İ[YJ	ÔÔU	ËÜ]\˜ÛÛ™T]
Bˆ\ÙÈ
ÏH›İ[YJ	ÓWĞĞÉËYÏ\Ù[‹YÊBˆY\ÜØYÙHH\ÙÂˆˆœÈH]Û“XZÙ\Š
BˆÈÙXİ[ÛˆˆRT”“ÔˆÑÔÏ‚ˆYˆÛÛ™šY×ÙXİÉÓRT”“Ô—ÓÑ×ÒQ	×H[™›İÙ[‹™^Ù\ØÚ]‚ˆWØœÈHY\ÛÜJ]ÛœÊBˆYˆÙ[‹œÛİ\˜ÙWİ\›[™ÛÛ™šY×ÙXİÉÔÓÕTÑWÓS’É×N‚ˆWØœËX]ÛŠ›İ[YJ	ÔÓÕTÑWÕT“	ÊKÙ[‹œÛİ\˜ÙWİ\›
BˆYˆÛÛ™šY×ÙXİÉÔĞU‘WÓTÑÉ×N‚ˆWØœËšX]ÛŠ›İ[YJ	ÔĞU‘WÓTÑÉÊK	ÜØ]™IË	Ù›Ûİ\‰ÊBˆÙ×Û\ÙÈH\İ

]ØZ]Ù[™][SY\ÜØYÙJÛÛ™šY×ÙXİÉÓRT”“Ô—ÓÑ×ÒQ	×KY\ÜØYÙKWØœË˜Z[ÛY[JŠKÙ[‹œ˜[™ÛWÜXÊJK˜[Y\Ê
JVÌBˆYˆÙ[‹›[šÜÛÙÛ\ÙÎ‚ˆ\Ü[YHH]][YK››İÊ[Y^›Û™JÛÛ™šY×ÙXİÉÕSQV“Ó‘I×JJKœİ™[YJ	ÉYÉ[KÉ^K	RN‰SN‰TÈ	\	ÊBˆØœÈH]Û“XZÙ\Š
BˆYˆÛÛ™šY×ÙXİÉÔĞU‘WÓTÑÉ×N‚ˆØœËšX]ÛŠ›İ[YJ	ÔĞU‘WÓTÑÉÊK	ÜØ]™IË	Ù›Ûİ\‰ÊBˆ]ØZ]Y]Y\ÜØYÙJÙ[‹›[šÜÛÙÛ\ÙË
\ÙÈ
È›İ[YJ	ÓS’Ô×ÔÓÕTÑIËÛY\Ü[YKÛİ\˜ÙO\Ù[‹œÛİ\˜ÙWÛ\ÙÊH
È›İ[YJ	ÓÓÓTÑÉÊH
Èˆ——H™YIŞÛÙ×Û\ÙË›[šßIÏÙ\ØØ\J˜[YJ_OØO—ˆŠKØœË˜Z[ÛY[JJJBˆˆÈÙXİ[ÛˆˆQTÔĞQÑHÑÔÏ‚ˆYˆÙ[‹š\ÔH[™Ù[‹š\Ôİ\\‘Ü›İ\‚ˆY\ÜØYÙH
ÏH›İ[YJ	ÓWĞ“ÕÓTÑÉÊBˆ]ÛœÈH^˜WØœÊ]ÛœÊVÌBˆœÈH^˜WØœÊœÊVÌBˆYˆÙ[‹š\ÔN‚ˆYˆÙ[‹š\Ôİ\\‘Ü›İ\‚ˆ×ØˆHY\ÛÜJœÊHYˆÛÛ™šY×ÙXİÉÓRT”“Ô—ÓÑ×ÒQ	×H[ÙHY\ÛÜJ]ÛœÊBˆYˆÙ[‹œÛİ\˜ÙWİ\›[™ÛÛ™šY×ÙXİÉÔÓÕTÑWÓS’É×N‚ˆ]ÛœËX]ÛŠ›İ[YJ	ÔÓÕTÑWÕT“	ÊKÙ[‹œÛİ\˜ÙWİ\›
BˆYˆ›İÛÛ™šY×ÙXİÉÔĞQ‘WÓSÑI×N‚ˆ×Ø‹X]ÛŠ›İ[YJ	ÔÓÕTÑWÕT“	ÊKÙ[‹œÛİ\˜ÙWİ\›
BˆYˆÙ[‹˜›İ[\ÙÎ‚ˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹˜›İ[\ÙËY\ÜØYÙK]ÛœË˜Z[ÛY[JŠKİÏ\Ù[‹œ˜[™ÛWÜXÊBˆYˆÛÛ™šY×ÙXİÉÔĞU‘WÓTÑÉ×N‚ˆ×Ø‹šX]ÛŠ›İ[YJ	ÔĞU‘WÓTÑÉÊK	ÜØ]™IË	Ù›Ûİ\‰ÊBˆ×Ø‹šX]ÛŠ›İ[YJ	ĞÒPÒ×ÔIÊKˆŞ›[İ\Ù\—ÚYH›İH‹	ÚXY\‰ÊBˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹›Y\ÜØYÙKY\ÜØYÙK×Ø‹˜Z[ÛY[JŠKİÏ\Ù[‹œ˜[™ÛWÜXÊBˆ[ÙN‚ˆYˆÙ[‹œÛİ\˜ÙWİ\›[™ÛÛ™šY×ÙXİÉÔÓÕTÑWÓS’É×N‚ˆ]ÛœËX]ÛŠ›İ[YJ	ÔÓÕTÑWÕT“	ÊKÙ[‹œÛİ\˜ÙWİ\›
Bˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹›Y\ÜØYÙKY\ÜØYÙK]ÛœË˜Z[ÛY[JŠKİÏ\Ù[‹œ˜[™ÛWÜXÊBˆ[ÙN‚ˆYˆÙ[‹œÛİ\˜ÙWİ\›[™ÛÛ™šY×ÙXİÉÔÓÕTÑWÓS’É×H[™
›İÙ[‹š\Ôİ\\‘Ü›İ\Üˆ›İÛÛ™šY×ÙXİÉÔĞQ‘WÓSÑI×JN‚ˆ]ÛœËX]ÛŠ›İ[YJ	ÔÓÕTÑWÕT“	ÊKÙ[‹œÛİ\˜ÙWİ\›
BˆYˆÛÛ™šY×ÙXİÉÔĞU‘WÓTÑÉ×H[™Ù[‹š\Ôİ\\‘Ü›İ\‚ˆ]ÛœËšX]ÛŠ›İ[YJ	ÔĞU‘WÓTÑÉÊK	ÜØ]™IË	Ù›Ûİ\‰ÊBˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹›Y\ÜØYÙKY\ÜØYÙK]ÛœË˜Z[ÛY[JŠKİÏ\Ù[‹œ˜[™ÛWÜXÊB‚ˆYˆÙ[‹œÙYY‚ˆYˆÙ[‹›™]Ñ\‚ˆ]ØZ]ÛX[—İ\™Ù]
Ù[‹›™]Ñ\ŠBˆ[YˆÙ[‹˜ÛÛ\™\ÜÎ‚ˆ]ØZ]ÛX[—İ\™Ù]
ˆÜÙ[‹™\ŸKŞÛ˜[Y_HŠBˆ\Ş[˜ÈÚ]]Y]YWÙXİÛØÚÎ‚ˆYˆÙ[‹ZY[ˆ›Û—Ü]Y]YYİ\‚ˆ›Û—Ü]Y]YYİ\œ™[[İ™JÙ[‹ZY
Bˆ]ØZ]İ\Ùœ›ÛWÜ]Y]YY

Bˆ™]\›‚ˆˆYˆÙ[‹˜›İ[\ÙÈ[™
›İÛÛ™šY×ÙXİÉÑSUWÓS’ÔÉ×HÜˆÛÛ™šY×ÙXİÉĞÓPS—ÓÑ×ÓTÑÉ×JN‚ˆ]ØZ][]SY\ÜØYÙJÙ[‹˜›İ[\ÙÊBˆˆ]ØZ]ÛX[—ÙİÛ›ØY
Ù[‹™\ŠBˆ\Ş[˜ÈÚ]İÛ›ØYÙXİÛØÚÎ‚ˆYˆÙ[‹ZY[ˆİÛ›ØYÙXİšÙ^\Ê
N‚ˆ[İÛ›ØYÙXİÜÙ[‹ZYBˆÛİ[H[ŠİÛ›ØYÙXİ
BˆYˆÛİ[OH‚ˆ]ØZ]Ù[‹˜ÛX[Š
Bˆ[ÙN‚ˆ]ØZ]\]WØ[ÛY\ÜØYÙ\Ê
B‚ˆ\Ş[˜ÈÚ]]Y]YWÙXİÛØÚÎ‚ˆYˆÙ[‹ZY[ˆ›Û—Ü]Y]YYİ\‚ˆ›Û—Ü]Y]YYİ\œ™[[İ™JÙ[‹ZY
B‚ˆ]ØZ]İ\Ùœ›ÛWÜ]Y]YY

Bˆ]ØZ][]WÛ[šÜÊÙ[‹›Y\ÜØYÙJB‚‚ˆ\Ş[˜ÈYˆÛ‘İÛ›ØY\œ›ÜŠÙ[‹\œ›Ü‹]ÛS›Û™JN‚ˆ\Ş[˜ÈÚ]İÛ›ØYÙXİÛØÚÎ‚ˆYˆÙ[‹ZY[ˆİÛ›ØYÙXİšÙ^\Ê
N‚ˆ[İÛ›ØYÙXİÜÙ[‹ZYBˆÛİ[H[ŠİÛ›ØYÙXİ
BˆYˆÙ[‹œØ[YQ\ˆ[™Ù[‹ZY[ˆÙ[‹œØ[YQ\–Éİ\ÚÜÉ×N‚ˆÙ[‹œØ[YQ\–Éİ\ÚÜÉ×Kœ™[[İ™JÙ[‹ZY
BˆÙ[‹œØ[YQ\–Éİİ[	×HOHBˆ\ÙÈH‰ÉÉÏO‘İÛ›ØYİÜYOØÚO‚¸¥(•\ÚÈ›ÜØˆÜÙ[‹YßB¸¥ Â¸¥(‘YHÎØˆÙ\ØØ\J\œ›ÜŠ_B¸¥(“[ÙNØˆÜÙ[‹\ØYÙ]Z[ÖÉÛ[ÙI×_B¸¥%ˆ‘[\ÙYØˆÙÙ]Ü™XYX›Wİ[YJ[YJ
HHÙ[‹›Y\ÜØYÙK™]K[Y\İ[\

J_IÉÉÂˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹›Y\ÜØYÙK\ÙË]ÛŠBˆYˆÛİ[OH‚ˆ]ØZ]Ù[‹˜ÛX[Š
Bˆ[ÙN‚ˆ]ØZ]\]WØ[ÛY\ÜØYÙ\Ê
B‚ˆYˆÙ[‹š\Ôİ\\‘Ü›İ\[™ÛÛ™šY×ÙXİÉÒSÓÓTUWÕTÒ×Ó“ÕQ’QT‰×H[™UPTÑWÕT“‚ˆ]ØZ]“X[™Ù\Š
Kœ›WØÛÛ\]Wİ\ÚÊÙ[‹›Y\ÜØYÙK›[šÊB‚ˆ\Ş[˜ÈÚ]]Y]YWÙXİÛØÚÎ‚ˆYˆÙ[‹ZY[ˆ]Y]YYÙ‚ˆ]Y]YYÙÜÙ[‹ZYKœÙ]

Bˆ[]Y]YYÙÜÙ[‹ZYBˆYˆÙ[‹ZY[ˆ]Y]YYİ\‚ˆ]Y]YYİ\ÜÙ[‹ZYKœÙ]

Bˆ[]Y]YYİ\ÜÙ[‹ZYBˆYˆÙ[‹ZY[ˆ›Û—Ü]Y]YYÙ‚ˆ›Û—Ü]Y]YYÙœ™[[İ™JÙ[‹ZY
BˆYˆÙ[‹ZY[ˆ›Û—Ü]Y]YYİ\‚ˆ›Û—Ü]Y]YYİ\œ™[[İ™JÙ[‹ZY
B‚ˆ]ØZ]İ\Ùœ›ÛWÜ]Y]YY

Bˆ]ØZ]ÛY\
ÊBˆ]ØZ]ÛX[—ÙİÛ›ØY
Ù[‹™\ŠBˆYˆÙ[‹›™]Ñ\‚ˆ]ØZ]ÛX[—ÙİÛ›ØY
Ù[‹›™]Ñ\ŠB‚ˆ\Ş[˜ÈYˆÛ•\ØY\œ›ÜŠÙ[‹\œ›ÜŠN‚ˆ\Ş[˜ÈÚ]İÛ›ØYÙXİÛØÚÎ‚ˆYˆÙ[‹ZY[ˆİÛ›ØYÙXİšÙ^\Ê
N‚ˆ[İÛ›ØYÙXİÜÙ[‹ZYBˆÛİ[H[ŠİÛ›ØYÙXİ
Bˆ\ÙÈH‰ÉÉÏO•\ØYİÜYOØÚO‚¸¥(•\ÚÈ›ÜØˆÜÙ[‹YßB¸¥ Â¸¥(‘YHÎØˆÙ\ØØ\J\œ›ÜŠ_B¸¥(“[ÙNØˆÜÙ[‹\ØYÙ]Z[ÖÉÛ[ÙI×_B¸¥%ˆ‘[\ÙYØˆÙÙ]Ü™XYX›Wİ[YJ[YJ
HHÙ[‹›Y\ÜØYÙK™]K[Y\İ[\

J_IÉÉÂˆ]ØZ]Ù[™Y\ÜØYÙJÙ[‹›Y\ÜØYÙK\ÙÊBˆYˆÛİ[OH‚ˆ]ØZ]Ù[‹˜ÛX[Š
Bˆ[ÙN‚ˆ]ØZ]\]WØ[ÛY\ÜØYÙ\Ê
B‚ˆYˆÙ[‹š\Ôİ\\‘Ü›İ\[™ÛÛ™šY×ÙXİÉÒSÓÓTUWÕTÒ×Ó“ÕQ’QT‰×H[™UPTÑWÕT“‚ˆ]ØZ]“X[™Ù\Š
Kœ›WØÛÛ\]Wİ\ÚÊÙ[‹›Y\ÜØYÙK›[šÊB‚ˆ\Ş[˜ÈÚ]]Y]YWÙXİÛØÚÎ‚ˆYˆÙ[‹ZY[ˆ]Y]YYÙ‚ˆ]Y]YYÙÜÙ[‹ZYKœÙ]

Bˆ[]Y]YYÙÜÙ[‹ZYBˆYˆÙ[‹ZY[ˆ]Y]YYİ\‚ˆ]Y]YYİ\ÜÙ[‹ZYKœÙ]

Bˆ[]Y]YYİ\ÜÙ[‹ZYBˆYˆÙ[‹ZY[ˆ›Û—Ü]Y]YYÙ‚ˆ›Û—Ü]Y]YYÙœ™[[İ™JÙ[‹ZY
BˆYˆÙ[‹ZY[ˆ›Û—Ü]Y]YYİ\‚ˆ›Û—Ü]Y]YYİ\œ™[[İ™JÙ[‹ZY
B‚ˆ]ØZ]İ\Ùœ›ÛWÜ]Y]YY

Bˆ]ØZ]ÛY\
ÊBˆ]ØZ]ÛX[—ÙİÛ›ØY
Ù[‹™\ŠBˆYˆÙ[‹›™]Ñ\‚ˆ]ØZ]ÛX[—ÙİÛ›ØY
Ù[‹›™]Ñ\ŠB
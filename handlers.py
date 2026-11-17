import secrets
from datetime import datetime, timedelta, timezone
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func
from app.db import Session
from app.models import User, Admin, Channel, Payment, Ticket
from app.config import settings

router = Router()
LANGS = {"fa":"فارسی","en":"English","ar":"العربية","fr":"Français","zh":"中文","ja":"日本語","hi":"हिन्दी","ru":"Русский","de":"Deutsch"}
MENU = {
"fa":["➕ افزودن کانال جدید","🖥 مدیریت کانال‌ها","🎁 تست رایگان ۲۴ ساعته","💰 خرید و شارژ","👤 حساب من","📚 راهنما","🌐 تغییر زبان","🎧 پشتیبانی","🛠 پنل مدیریت"],
"en":["➕ Add channel","🖥 Manage channels","🎁 24-hour free trial","💰 Buy / Top up","👤 My account","📚 Guide","🌐 Language","🎧 Support","🛠 Admin panel"]}
def now(): return datetime.now(timezone.utc)
def kb(lang, admin=False):
    labels=MENU["en"] if lang=="en" else MENU["fa"]
    rows=[[KeyboardButton(text=labels[0]),KeyboardButton(text=labels[1])],[KeyboardButton(text=labels[2])],[KeyboardButton(text=labels[3]),KeyboardButton(text=labels[4])],[KeyboardButton(text=labels[5]),KeyboardButton(text=labels[6])],[KeyboardButton(text=labels[7])]]
    if admin: rows.append([KeyboardButton(text=labels[8])])
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True)
async def getuser(tg):
    async with Session() as s:
        u=await s.scalar(select(User).where(User.tg_id==tg.id))
        if not u:
            code=tg.language_code if tg.language_code in LANGS else "fa"
            u=User(tg_id=tg.id,first_name=tg.first_name or "",last_name=tg.last_name or "",username=tg.username,language=code)
            s.add(u); await s.commit(); await s.refresh(u)
        else:
            u.first_name=tg.first_name or ""; u.last_name=tg.last_name or ""; u.username=tg.username; await s.commit()
        return u
async def admin(tg):
    async with Session() as s:
        a=await s.scalar(select(Admin).where(Admin.tg_id==tg.id))
        if a: return True
        if tg.username and tg.username.lower() in settings.initial_admins:
            s.add(Admin(tg_id=tg.id,username=tg.username)); await s.commit(); return True
        return False
def trial_active(u): return bool(u.trial_ends_at and u.trial_ends_at > now())
async def access(uid):
    async with Session() as s:
        u=await s.get(User,uid)
        if not u or u.blocked: return False
        if trial_active(u): return True
        cs=(await s.scalars(select(Channel).where(Channel.owner_id==uid,Channel.enabled==True))).all()
        return any(c.active_until>now() for c in cs)
@router.message(CommandStart())
async def start(m:Message):
    u=await getuser(m.from_user)
    await m.answer("✨ به ربات مدیریت ری‌اکشن خوش آمدید",reply_markup=kb(u.language,await admin(m.from_user)))
@router.message(Command("id"))
async def idcmd(m): await m.answer(f"آیدی عددی شما: <code>{m.from_user.id}</code>")
@router.message(F.chat.type.in_({"group","supergroup"}),Command("connect"))
async def connect(m):
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: return await m.reply("فرمت: /connect TOKEN")
    async with Session() as s:
        c=await s.scalar(select(Channel).where(Channel.token==p[1].strip(),Channel.enabled==True))
        if not c: return await m.reply("توکن اتصال نامعتبر است.")
        c.report_group_id=m.chat.id; await s.commit()
    await m.reply("✅ گروه گزارش متصل شد.")
@router.message(F.chat.type=="channel")
async def post(m):
    async with Session() as s:
        c=await s.scalar(select(Channel).where(Channel.chat_id==m.chat.id,Channel.enabled==True))
        if not c or c.active_until<=now(): return
        try: await m.bot.set_message_reaction(chat_id=m.chat.id,message_id=m.message_id,reaction=[{"type":"emoji","emoji":c.emoji}])
        except Exception: pass
        txt=f"📢 پست جدید در {c.title}\nشناسه: {m.message_id}"
        if c.report_group_id:
            try: await m.bot.send_message(c.report_group_id,txt)
            except Exception: pass
        else:
            u=await s.get(User,c.owner_id)
            try: await m.bot.send_message(u.tg_id,txt)
            except Exception: pass
@router.message(F.reply_to_message,F.chat.type.in_({"group","supergroup"}))
async def manual(m):
    emoji=(m.text or "").strip().split()[0] if m.text else ""
    if not emoji: return
    try:
        await m.bot.set_message_reaction(chat_id=m.chat.id,message_id=m.reply_to_message.message_id,reaction=[{"type":"emoji","emoji":emoji}])
        await m.reply("✅ یک ری‌اکشن از طرف ربات ثبت شد.")
    except Exception: await m.reply("❌ ثبت ری‌اکشن ممکن نشد.")
@router.message(F.text)
async def menu(m):
    u=await getuser(m.from_user); t=m.text
    if t in ("🎁 تست رایگان ۲۴ ساعته","🎁 24-hour free trial"):
        async with Session() as s:
            x=await s.get(User,u.id)
            if x.trial_used: return await m.answer("⛔ تست رایگان قبلاً استفاده شده است.")
            x.trial_used=True; x.trial_ends_at=now()+timedelta(hours=settings.trial_hours); await s.commit()
        return await m.answer("🎁 تست ۲۴ ساعته شما فعال شد.")
    if t in ("👤 حساب من","👤 My account"):
        async with Session() as s:
            x=await s.get(User,u.id); cs=(await s.scalars(select(Channel).where(Channel.owner_id==u.id))).all()
            active=[c for c in cs if c.enabled and c.active_until>now()]
            exp=max((c.active_until for c in active),default=None)
            await m.answer(f"👤 <b>حساب شما</b>\n\n🆔 آیدی: <code>{x.tg_id}</code>\n👤 نام: {x.first_name} {x.last_name}\n🔗 یوزرنیم: @{x.username or 'ندارد'}\n💎 کوین: {x.coins}\n📡 کانال فعال: {len(active)}\n📅 اشتراک تا: {exp.strftime('%Y-%m-%d') if exp else ('تست فعال' if trial_active(x) else 'ندارد')}\n📊 ری‌اکشن: یک واکنش از حساب ربات\n\nهر کوین = یک کانال برای ۳۰ روز")
        return
    if t in ("📚 راهنما","📚 Guide"):
        return await m.answer("📚 راهنمای استفاده\n۱) از خرید و شارژ کوین تهیه کن (هر کانال = یک کوین برای یک ماه).\n۲) با افزودن کانال جدید کانالت را معرفی کن.\n۳) یک گروه خصوصی بساز، ربات را اضافه کن و دستور /connect TOKEN را در گروه بفرست.\n۴) از مدیریت کانال‌ها وضعیت کانال‌ها را ببین.\n\n🤖 ربات روی پست جدید یک ری‌اکشن ثبت و گزارش ارسال می‌کند.\n⚠️ محدودیت Bot API: یک واکنش از حساب ربات برای هر پیام؛ ثبت ۵۰ واکنش واقعی با یک ربات ممکن نیست.")
    if t in ("🌐 تغییر زبان","🌐 Language"):
        buttons=[[InlineKeyboardButton(text=v,callback_data=f"lang:{k}")] for k,v in LANGS.items()]
        return await m.answer("زبان را انتخاب کنید:",reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    if t in ("➕ افزودن کانال جدید","➕ Add channel"):
        if not await access(u.id): return await m.answer("🔒 ابتدا تست را فعال کنید یا کوین تهیه کنید.")
        return await m.answer("ربات را در کانال مدیر کنید و سپس @username یا شناسه عددی کانال را ارسال کنید.")
    if t in ("🖥 مدیریت کانال‌ها","🖥 Manage channels"):
        async with Session() as s:
            cs=(await s.scalars(select(Channel).where(Channel.owner_id==u.id))).all()
            if not cs: return await m.answer("هنوز کانالی ثبت نکرده‌اید.")
            for c in cs: await m.answer(f"📡 {c.title}\nایموجی: {c.emoji}\nانقضا: {c.active_until:%Y-%m-%d}\nتوکن اتصال گروه: <code>{c.token}</code>")
        return
    if t in ("💰 خرید و شارژ","💰 Buy / Top up"):
        return await m.answer("برای درخواست شارژ بنویسید: <code>شارژ 3</code> (عدد را با تعداد کوین جایگزین کنید). مدیر درخواست را بررسی می‌کند.")
    if t in ("🎧 پشتیبانی","🎧 Support"):
        return await m.answer("پیام خود را به شکل زیر بفرستید: <code>پشتیبانی متن پیام</code>")
    if t.startswith("شارژ "):
        try: amount=int(t.split()[1]); assert 1<=amount<=1000
        except: return await m.answer("فرمت درست: شارژ 3")
        async with Session() as s:
            x=await s.get(User,u.id); p=Payment(user_id=x.id,coins=amount); s.add(p); await s.commit(); await s.refresh(p)
            admins=(await s.scalars(select(Admin))).all()
            for a in admins:
                try: await m.bot.send_message(a.tg_id,f"درخواست شارژ #{p.id} | کاربر {x.tg_id} | {amount} کوین",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="تأیید",callback_data=f"payok:{p.id}"),InlineKeyboardButton(text="رد",callback_data=f"payno:{p.id}")]]))
                except: pass
        return await m.answer("✅ درخواست برای مدیر ارسال شد.")
    if t.startswith("پشتیبانی "):
        body=t[len("پشتیبانی "):]
        async with Session() as s:
            s.add(Ticket(user_id=u.id,message=body)); await s.commit()
            admins=(await s.scalars(select(Admin))).all()
            for a in admins:
                try: await m.bot.send_message(a.tg_id,f"🎧 پشتیبانی از {u.tg_id}:\n{body}")
                except: pass
        return await m.answer("✅ پیام پشتیبانی ارسال شد.")
    if t.startswith("@") or t.lstrip("-").isdigit():
        if not await access(u.id): return await m.answer("اشتراک فعال ندارید.")
        try:
            chat=await m.bot.get_chat(t); me=await m.bot.get_me(); member=await m.bot.get_chat_member(chat.id,me.id)
            if member.status not in ("administrator","creator"): return await m.answer("ابتدا ربات را در کانال مدیر کنید.")
            async with Session() as s:
                x=await s.get(User,u.id)
                if x.coins<1 and not trial_active(x): return await m.answer("کوین کافی ندارید.")
                if x.coins>0:
                    x.coins-=1
                    expiry=now()+timedelta(days=30)
                else:
                    expiry=x.trial_ends_at
                c=Channel(owner_id=x.id,chat_id=chat.id,title=chat.title or str(chat.id),token=secrets.token_urlsafe(7),active_until=expiry)
                s.add(c); await s.commit()
            return await m.answer(f"✅ کانال ثبت شد. برای اتصال گروه، ربات را به گروهی که خودتان ساخته‌اید اضافه کنید و بفرستید:\n<code>/connect {c.token}</code>")
        except Exception: return await m.answer("❌ کانال پیدا نشد یا ربات مدیر کانال نیست.")
    if t in ("🛠 پنل مدیریت","🛠 Admin panel") and await admin(m.from_user):
        return await m.answer("🛠 پنل مدیریت",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 آمار",callback_data="stats"),InlineKeyboardButton(text="👥 کاربران",callback_data="users")],[InlineKeyboardButton(text="📨 شارژها",callback_data="payments")]]))
@router.callback_query(F.data.startswith("lang:"))
async def setlang(c):
    code=c.data.split(":")[1]
    async with Session() as s:
        u=await s.scalar(select(User).where(User.tg_id==c.from_user.id)); u.language=code; await s.commit()
    await c.message.answer("✅ زبان ذخیره شد.",reply_markup=kb(code,await admin(c.from_user))); await c.answer()
@router.callback_query(F.data.in_({"stats","users","payments"}))
async def admin_panel(c):
    if not await admin(c.from_user): return await c.answer("دسترسی ندارید",show_alert=True)
    async with Session() as s:
        if c.data=="stats":
            n=await s.scalar(select(func.count(User.id))); nc=await s.scalar(select(func.count(Channel.id)))
            await c.message.answer(f"📊 کاربران: {n}\nکانال‌ها: {nc}")
        elif c.data=="users":
            us=(await s.scalars(select(User).order_by(User.id.desc()).limit(30))).all()
            await c.message.answer("\n".join(f"{x.tg_id} | @{x.username or '-'} | کوین {x.coins}" for x in us) or "کاربری ثبت نشده")
        else:
            ps=(await s.scalars(select(Payment).where(Payment.status=="pending"))).all()
            for p in ps: await c.message.answer(f"شارژ #{p.id} | {p.coins} کوین",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="تأیید",callback_data=f"payok:{p.id}"),InlineKeyboardButton(text="رد",callback_data=f"payno:{p.id}")]]))
    await c.answer()
@router.callback_query(F.data.startswith("payok:"))
async def payok(c):
    if not await admin(c.from_user): return await c.answer("دسترسی ندارید",show_alert=True)
    pid=int(c.data.split(":")[1])
    async with Session() as s:
        p=await s.get(Payment,pid)
        if not p or p.status!="pending": return await c.answer("قبلاً بررسی شده")
        p.status="approved"; u=await s.get(User,p.user_id); u.coins+=p.coins; tg=u.tg_id; amount=p.coins; await s.commit()
    await c.bot.send_message(tg,f"✅ {amount} کوین به حساب شما اضافه شد."); await c.message.edit_text("درخواست تأیید شد."); await c.answer()
@router.callback_query(F.data.startswith("payno:"))
async def payno(c):
    if not await admin(c.from_user): return await c.answer("دسترسی ندارید",show_alert=True)
    async with Session() as s:
        p=await s.get(Payment,int(c.data.split(":")[1]))
        if p: p.status="rejected"; await s.commit()
    await c.message.edit_text("درخواست رد شد."); await c.answer()
@router.message(Command("credit"))
async def credit(m):
    if not await admin(m.from_user): return
    try:
        _,uid,amount=m.text.split()
        async with Session() as s:
            u=await s.scalar(select(User).where(User.tg_id==int(uid))); u.coins+=int(amount); await s.commit()
        await m.answer("موجودی به‌روزرسانی شد.")
    except: await m.answer("فرمت: /credit USER_ID COINS")
@router.message(Command("addadmin"))
async def addadmin(m):
    if not await admin(m.from_user): return
    try:
        uid=int(m.text.split()[1])
        async with Session() as s:
            u=await s.scalar(select(User).where(User.tg_id==uid))
            if not u: raise ValueError()
            if not await s.scalar(select(Admin).where(Admin.tg_id==uid)): s.add(Admin(tg_id=uid,username=u.username)); await s.commit()
        await m.answer("مدیر اضافه شد.")
    except: await m.answer("کاربر باید ابتدا /start زده باشد. فرمت: /addadmin USER_ID")
@router.message(Command("broadcast"))
async def broadcast(m):
    if not await admin(m.from_user): return
    body=m.text.partition(" ")[2].strip()
    if not body: return await m.answer("فرمت: /broadcast متن")
    async with Session() as s: ids=(await s.scalars(select(User.tg_id).where(User.blocked==False))).all()
    sent=0
    for uid in ids:
        try: await m.bot.send_message(uid,body); sent+=1
        except: pass
    await m.answer(f"ارسال شد: {sent}/{len(ids)}")

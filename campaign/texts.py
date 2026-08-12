"""User-facing campaign texts."""

from __future__ import annotations

from .config import (
    BANK_DISPLAY,
    CAMPAIGN_END,
    CAMPAIGN_START,
    REWARD_MILESTONES,
    STATUS_ACCEPTED,
    STATUS_DUPLICATE,
    STATUS_FAKE,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_REVERSED,
    STATUS_UNSUPPORTED,
    format_money_kopecks,
)

STATUS_LABEL = {
    STATUS_PENDING: "⏳ на проверке",
    STATUS_ACCEPTED: "✅ принят",
    STATUS_REJECTED: "❌ отклонён",
    STATUS_DUPLICATE: "❌ дубликат",
    STATUS_FAKE: "🔴 подделка",
    STATUS_UNSUPPORTED: "⚪ не поддержан",
    STATUS_REVERSED: "⚠️ отменён",
}


def rules_text() -> str:
    banks = ", ".join(BANK_DISPLAY[k] for k in sorted(BANK_DISPLAY))
    miles = "\n".join(
        f"• {n} принятых чеков — {rub:,} ₽".replace(",", " ")
        for n, rub in REWARD_MILESTONES
    )
    start = CAMPAIGN_START.strftime("%d.%m.%Y")
    end = CAMPAIGN_END.strftime("%d.%m.%Y %H:%M")
    return (
        f"📋 <b>Правила акции</b>\n\n"
        f"Период: <b>{start}</b> — <b>{end}</b> (МСК)\n"
        f"Выплаты: после окончания акции.\n\n"
        f"Принимаются <b>оригинальные PDF-чеки</b> банков:\n{banks}\n\n"
        f"Условия:\n"
        f"• дата операции не ранее 19.07.2026\n"
        f"• банк распознан и поддерживается\n"
        f"• операция завершена\n"
        f"• чек признан оригиналом\n"
        f"• документ и операция уникальны\n\n"
        f"Начисление:\n{miles}\n\n"
        f"Реферальной программы нет."
    )


def profile_text(user_id: int, username: str | None, snap: dict) -> str:
    uname = f"@{username}" if username else "—"
    return (
        f"👤 <b>Мой профиль</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Username: {uname}\n\n"
        f"<b>Акция:</b> 1 принятый оригинальный чек = 10 ₽\n"
        f"Статистика ниже — только по этой акции.\n\n"
        f"Загружено чеков: <b>{snap['uploaded']}</b>\n"
        f"Принято: <b>{snap['accepted']}</b>\n"
        f"Отклонено: <b>{snap['rejected']}</b>\n\n"
        f"Баланс к выплате: <b>{snap['balance_text']}</b>\n"
        f"Выплаты: после окончания акции"
    )


def stats_text(snap: dict) -> str:
    return (
        f"💰 <b>Статистика акции</b>\n\n"
        f"Акция: 1 принятый оригинальный чек = 10 ₽\n\n"
        f"Загружено: <b>{snap['uploaded']}</b>\n"
        f"Принято: <b>{snap['accepted']}</b>\n"
        f"Отклонено: <b>{snap['rejected'] + snap.get('unsupported', 0)}</b>\n\n"
        f"К выплате после окончания акции: <b>{snap['balance_text']}</b>"
    )


def checks_list_text(rows: list[dict]) -> str:
    if not rows:
        return "📄 <b>Мои чеки по акции</b>\n\nПока нет загрузок по акции."
    lines = ["📄 <b>Мои чеки по акции</b>\n"]
    for r in rows:
        bank = r.get("bank_name") or BANK_DISPLAY.get(r.get("bank_key") or "", "—")
        st = STATUS_LABEL.get(r.get("status") or "", r.get("status") or "?")
        lines.append(f"#{r['id']} — {bank} — {st}")
    return "\n".join(lines)


def _fmt_dt(raw: str | None) -> str:
    """Human date without timezone offset like +0300."""
    if not raw:
        return "—"
    s = str(raw).strip()
    # 2026-07-19 21:37:02+0300 / +03:00
    for sep in ("+", "-"):
        # only strip trailing tz if looks like "...HH:MM:SS+0300"
        if len(s) > 19 and s[19] in "+-" and s[10] == " ":
            s = s[:19]
            break
    if s.endswith("Z"):
        s = s[:-1]
    return s.replace("T", " ")


def check_detail_text(row: dict) -> str:
    bank = row.get("bank_name") or BANK_DISPLAY.get(row.get("bank_key") or "", "—")
    st = STATUS_LABEL.get(row.get("status") or "", row.get("status") or "?")
    reward = int(row.get("reward_kopecks") or 0)
    lines = [
        f"📄 <b>Чек #{row['id']}</b>",
        f"Банк: {bank}",
        f"Загружен: {_fmt_dt(row.get('created_at'))}",
        f"Статус: {st}",
    ]
    if row.get("status") == STATUS_ACCEPTED:
        lines.append(f"Начислено: {format_money_kopecks(reward)}")
    reason = row.get("reject_reason_text")
    if reason and row.get("status") not in (STATUS_ACCEPTED, STATUS_PENDING):
        lines.append(f"Причина: {reason}")
    return "\n".join(lines)


def notify_accepted(snap: dict) -> str:
    return (
        f"✅ <b>Чек принят</b>\n"
        f"Принято чеков: <b>{snap['accepted']}</b>\n"
        f"К выплате после окончания акции: <b>{snap['balance_text']}</b>"
    )


def notify_rejected(reason: str) -> str:
    return f"❌ <b>Чек не принят</b>\nПричина: {reason}"


def notify_reversed(reason: str) -> str:
    return (
        f"⚠️ <b>Начисление отменено</b>\n"
        f"Причина: {reason or 'документ признан поддельным после дополнительной проверки'}"
    )

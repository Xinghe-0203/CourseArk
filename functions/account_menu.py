"""账号管理与多选；保存后不必再次手动输入密码。"""
from loguru import logger
from rich.prompt import Prompt
from core.selection import parse_selection
from models.user import User


def _save_account(store, existing=None):
    username = existing['username'] if existing else Prompt.ask('手机号').strip()
    if username.lower() == 'q':
        raise KeyboardInterrupt()
    import re
    if not re.fullmatch(r'1\d{10}', username):
        raise ValueError('请输入有效手机号，q 返回')
    password = Prompt.ask('密码', password=True)
    label = Prompt.ask('账号备注（可空）', default=existing.get('label', '') if existing else '')
    # 登录验证成功再替换凭据，错误密码不覆盖已保存账号。
    user = User(username, password)
    user.get_courses()
    account = store.upsert(username, password, label)
    store.save_session(account['id'], user.export_session())
    logger.success('账号已保存，下次可直接选择')
    return account['id']


def select_accounts(tui, store, current=None):
    """返回多个账号 ID；q 返回本次空选择，主菜单保留原选择。"""
    current = current if current is not None else store.selected_ids
    while True:
        accounts = store.list_accounts()
        if not accounts:
            try:
                current = [_save_account(store)]
            except (KeyboardInterrupt, EOFError):
                return []
            except Exception as exc:
                logger.error(f'账号未保存：{exc}')
            continue
        tui.show_accounts(accounts, current)
        defaults = ','.join(str(i + 1) for i, a in enumerate(accounts) if a['id'] in current)
        choice = Prompt.ask('账号序号（多选逗号分隔/all全选/n新增/e序号修改/d序号删除/q返回）', default=defaults or 'all').strip()
        if choice.lower() == 'q':
            return []
        try:
            if choice.lower() == 'n':
                account_id = _save_account(store)
                current = list(dict.fromkeys([*current, account_id]))
                continue
            if choice[:1].lower() in ('e', 'd'):
                if not choice[1:].strip():
                    raise ValueError('请在操作后填写账号序号，例如 e1 或 d1')
                indices = parse_selection(choice[1:], len(accounts))
                if len(indices) != 1:
                    raise ValueError('修改或删除时请输入一个账号序号')
                account_id = accounts[indices[0]]['id']
                if choice[0].lower() == 'd':
                    store.delete(account_id)
                    current = [i for i in current if i != account_id]
                    logger.info('已删除此账号及保存的会话')
                else:
                    _save_account(store, store.get(account_id))
                continue
            selected = [accounts[i]['id'] for i in parse_selection(choice, len(accounts))]
            store.set_selected(selected)
            return selected
        except (KeyboardInterrupt, EOFError):
            return []
        except Exception as exc:
            logger.error(str(exc))

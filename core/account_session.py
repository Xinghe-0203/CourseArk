"""优先恢复会话，明确失效时才重新认证。"""
from core.exceptions import CookieExpiredException
from core.request_client import get_session
from models.user import User


def open_account(account):
    """调用方必须独占本进程的 RequestClient，不可按账号开启线程。"""
    get_session().cookies.clear()
    session = account.get('session') or {}
    if session:
        try:
            user = User.from_session(account['username'], session)
            user.get_courses()
            return user
        except CookieExpiredException:
            get_session().cookies.clear()
    user = User(account['username'], account['password'])
    user.get_courses()
    return user


class AccountSessions:
    def __init__(self, store):
        self.store = store

    def open(self, account_id):
        user = open_account(self.store.get(account_id))
        self.store.save_session(account_id, user.export_session())
        return user

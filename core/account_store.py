"""本地 CLI 账号库；只有主进程写入，避免并行账号互相覆盖。"""
import copy
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

from core.paths import get_user_data_path


def mask_phone(phone: str) -> str:
    return phone[:3] + '****' + phone[-4:] if len(phone) == 11 else '未设置'


class AccountStore:
    def __init__(self, path=None):
        self.path = Path(path or get_user_data_path('data/cli_accounts.json')).resolve()
        self._data = {'version': 1, 'accounts': [], 'selected': []}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(data, dict) or data.get('version') != 1:
                    raise ValueError('格式无效')
                accounts, selected = data.get('accounts'), data.get('selected')
                if not isinstance(accounts, list) or not isinstance(selected, list):
                    raise ValueError('格式无效')
                ids, phones = set(), set()
                for a in accounts:
                    if (not isinstance(a, dict) or not isinstance(a.get('id'), str)
                            or not a['id'] or a['id'] in ids
                            or not re.fullmatch(r'1\d{10}', str(a.get('username', '')))
                            or a['username'] in phones
                            or not isinstance(a.get('password'), str) or not a['password']
                            or not isinstance(a.get('label', ''), str)
                            or not isinstance(a.get('session', {}), dict)):
                        raise ValueError('账号记录无效')
                    ids.add(a['id']); phones.add(a['username'])
                if any(not isinstance(i, str) for i in selected):
                    raise ValueError('选择记录无效')
                data['selected'] = list(dict.fromkeys(i for i in selected if i in ids))
                self._data = data
            except (ValueError, TypeError, OSError, KeyError) as exc:
                raise ValueError(f'账号库读取失败，原文件已保留：{self.path}。请修复文件或备份后移走再启动。') from exc

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.path.parent,
                                             prefix=self.path.name + '.', suffix='.tmp', delete=False) as f:
                temp_path = f.name
                try:
                    os.chmod(temp_path, 0o600)
                except OSError:
                    pass  # FAT32 不支持 Unix 权限。
                json.dump(self._data, f, ensure_ascii=False, indent=2)
                f.flush(); os.fsync(f.fileno())
            os.replace(temp_path, self.path)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    @property
    def selected_ids(self):
        return list(self._data['selected'])

    def get(self, account_id):
        for a in self._data['accounts']:
            if a['id'] == account_id:
                return copy.deepcopy(a)
        raise KeyError('账号不存在')

    def list_accounts(self):
        return [{'id': a['id'], 'username': mask_phone(a['username']),
                 'label': a.get('label') or mask_phone(a['username']),
                 'has_session': bool(a.get('session'))} for a in self._data['accounts']]

    def upsert(self, username, password, label=''):
        username, label = str(username).strip(), str(label).strip()
        if not re.fullmatch(r'1\d{10}', username) or not isinstance(password, str) or not password:
            raise ValueError('请输入有效的手机号和非空密码')
        a = next((a for a in self._data['accounts'] if a['username'] == username), None)
        if a is None:
            a = {'id': uuid.uuid4().hex, 'username': username, 'password': password,
                 'label': label, 'session': {}}
            self._data['accounts'].append(a)
        else:
            if a['password'] != password:
                a['session'] = {}
            a['password'] = password
            a['label'] = label or a.get('label', '')
        self._save()
        return copy.deepcopy(a)

    def import_legacy(self, account):
        phone, password = account.get('phone', ''), account.get('password', '')
        if phone and password and not any(a['username'] == str(phone) for a in self._data['accounts']):
            a = self.upsert(phone, password)
            if not self.selected_ids:
                self.set_selected([a['id']])

    def save_session(self, account_id, session):
        if not isinstance(session, dict):
            raise ValueError('会话数据格式无效')
        self.get(account_id)
        for a in self._data['accounts']:
            if a['id'] == account_id:
                a['session'] = copy.deepcopy(session)
                self._save()
                return

    def set_selected(self, ids):
        valid = {a['id'] for a in self._data['accounts']}
        self._data['selected'] = list(dict.fromkeys(i for i in ids if i in valid))
        self._save()

    def delete(self, account_id):
        self.get(account_id)
        self._data['accounts'] = [a for a in self._data['accounts'] if a['id'] != account_id]
        self._data['selected'] = [i for i in self._data['selected'] if i != account_id]
        self._save()

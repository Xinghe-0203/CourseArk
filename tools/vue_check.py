"""多账号 Vue 验收：临时数据目录、停用调度，不连接学习通。"""
import json, re, socket, sys, threading, time
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright
from ui_check import prepare, launch_browser
ROOT=Path(__file__).resolve().parents[1]

def check(url, output):
    checks, errors=[],[]
    def passed(name): checks.append({'name':name,'ok':True})
    with sync_playwright() as p:
        browser=launch_browser(p)
        page=browser.new_page(viewport={'width':1920,'height':1080})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(url)
        page.locator('.execution-account').first.wait_for()
        assert page.locator('.execution-account').count()==2
        assert page.locator('.execution-course').count()==2
        assert page.locator('.media-live li').count()==4
        assert page.get_by_text('账号 03',exact=True).count()==0
        assert page.get_by_text('账号 06',exact=True).count()==0
        heights=page.locator('.execution-account').evaluate_all('(nodes)=>nodes.map(n=>Math.round(n.getBoundingClientRect().height))')
        assert heights==[520,520]
        assert page.locator('.execution-dashboard').count()==1
        passed('总览只显示执行中的两个账号与课程，固定520px卡片与真实进度仪表盘')
        # 运行中进度小窗：当前动作、已用时、预计剩余，可最小化/展开
        win=page.locator('.progress-window')
        win.wait_for()
        text=win.inner_text()
        assert '已用时' in text and '预计剩余' in text
        page.wait_for_function('document.querySelector(".progress-window-activity")?.textContent.includes("正在学习")',timeout=10000)
        assert re.search(r'\d{2}:\d{2}:\d{2}',win.inner_text())
        win.get_by_role('button',name='最小化进度小窗').click()
        page.wait_for_function('document.querySelectorAll(".progress-window-body").length===0')
        win.get_by_role('button',name='展开进度小窗').click()
        page.locator('.progress-window-body').wait_for()
        page.screenshot(path=str(output/'desktop-progress-window.png'))
        passed('运行进度小窗显示当前动作/已用时/预计剩余，可最小化与展开')
        for width,height,name in [(1920,1080,'wide'),(1440,1000,'desktop'),(390,844,'mobile')]:
            page.set_viewport_size({'width':width,'height':height})
            for title in ['工作总览','账号与课程','学习任务','答题缓存','问题中心','偏好设置']:
                page.get_by_role('navigation',name='主要导航').get_by_role('button',name=title).click()
                page.get_by_role('heading',name=title,exact=True).wait_for()
                page.wait_for_timeout(180)
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'),(name,title)
                passed(name+' / '+title+' 无横向溢出')
                page.screenshot(path=str(output/f'{name}-{title}.png'),full_page=True)
                if name=='mobile' and title=='工作总览': page.screenshot(path=str(output/'mobile-viewport.png'))
        page.set_viewport_size({'width':1440,'height':1000})
        nav=page.get_by_role('navigation',name='主要导航')
        nav.get_by_role('button',name='学习任务').click()
        profiles=page.locator('.workspace-account')
        profiles.first.wait_for()
        assert profiles.count()==6
        assert len(set(profiles.evaluate_all('(nodes)=>nodes.map(n=>Math.round(n.getBoundingClientRect().height))')))==1
        assert page.locator('.workspace-course').count()==18
        passed('学习任务保留六账号完整数据，全部账号卡片固定高度')
        profiles.nth(2).locator('.workspace-course input:not(:disabled)').first.check()
        for i in (0,1): profiles.nth(i).locator('.workspace-account-head input').check()
        page.get_by_role('button',name='创建所选 1 门课程任务',exact=True).click()
        cross=page.get_by_role('dialog');cross.wait_for()
        assert cross.locator('.wizard-account input:checked').count()==1
        assert cross.locator('.wizard-account input:checked').input_value()==page.request.get(url+'/api/workspace/accounts').json()['items'][2]['account']['id']
        cross.get_by_role('button',name='下一步：选择课程',exact=True).click()
        cross.locator('.course-option input:checked').first.wait_for()
        assert cross.locator('.course-option input:checked').count()==1
        page.keyboard.press('Escape')
        passed('所选课程创建以课程所属账号为范围，不被无关账号勾选覆盖')
        selected_ids={p['account']['id'] for p in page.request.get(url+'/api/workspace/accounts').json()['items'][:2]}
        page.get_by_label('搜索账号工作台').fill('账号 02')
        assert profiles.count()==1
        page.get_by_role('button',name='批量暂停',exact=True).click()
        page.get_by_text('已接受 2 项暂停操作',exact=True).wait_for()
        values=page.request.get(url+'/api/workspace/accounts').json()['items']
        assert all(p['tasks'][0]['status']=='pausing' for p in values[:2])
        passed('搜索隐藏的已选账号仍参与批量暂停，服务端接受数准确')
        page.get_by_label('搜索账号工作台').fill('')
        page.get_by_role('button',name='紧凑展开',exact=True).click()
        nav.get_by_role('button',name='账号与课程').click()
        nav.get_by_role('button',name='学习任务').click()
        assert profiles.locator('.workspace-account-head input:checked').count()==2
        assert page.locator('.account-workspaces.compact').count()==1
        passed('账号选择与紧凑布局跨页面保留')
        page.screenshot(path=str(output/'desktop-compact.png'),full_page=True)
        page.get_by_role('button',name='所选账号开始',exact=True).click()
        dialog=page.get_by_role('dialog');dialog.wait_for()
        assert dialog.locator('.wizard-account input:checked').count()==2
        assert dialog.locator('.course-picker').count()==0
        assert dialog.get_by_role('button',name='创建 4 项任务',exact=True).count()==0
        page.screenshot(path=str(output/'desktop-wizard-accounts.png'))
        dialog.get_by_role('button',name='下一步：选择课程',exact=True).click()
        dialog.locator('.course-option input:checked').first.wait_for()
        assert dialog.locator('.course-picker section').count()==2
        assert dialog.locator('.course-option input:checked').count()==4
        assert [s.strip() for s in dialog.locator('.feature-grid button').all_text_contents()]==['课程任务点','独立作业','独立考试']
        dialog.get_by_role('button',name='上一步：选择账号',exact=True).click()
        dialog.locator('.wizard-account input:checked').first.uncheck()
        dialog.get_by_role('button',name='下一步：选择课程',exact=True).click()
        dialog.locator('.course-option input:checked').first.wait_for()
        assert dialog.locator('.course-picker section').count()==1
        assert dialog.locator('.course-option input:checked').count()==2
        dialog.get_by_role('button',name='上一步：选择账号',exact=True).click()
        dialog.locator('.wizard-account input').first.check()
        dialog.get_by_role('button',name='下一步：选择课程',exact=True).click()
        dialog.get_by_role('button',name='全选可学习课程',exact=True).wait_for(state='visible')
        page.wait_for_function('document.querySelectorAll(".course-option").length===5')
        dialog.get_by_role('button',name='全选可学习课程',exact=True).click()
        page.screenshot(path=str(output/'desktop-wizard-courses.png'))
        passed('新建任务两步选择，返回改账号清理跨账号残留，全选课程保留账号身份')
        dialog.get_by_role('button',name='独立作业',exact=True).click()
        with page.expect_response(lambda r:r.url.endswith('/api/runs') and r.request.method=='POST') as created:
            page.get_by_role('button',name='创建 4 项任务',exact=True).click()
        assert created.value.status==201
        payload=created.value.request.post_data_json
        assert payload['feature']=='independent_homework'
        assert {t['account_id'] for t in payload['targets']}==selected_ids
        assert len({(t['account_id'],t['course_id'],t['class_id']) for t in payload['targets']})==4
        page.wait_for_selector('.modal',state='detached')
        passed('仅两个模块，所选账号开始排除残留课程，同名课程账号隔离')
        profiles.first.get_by_role('button',name='创建任务',exact=True).click()
        dialog.wait_for()
        assert dialog.locator('.wizard-account input:checked').count()==1
        dialog.get_by_role('button',name='下一步：选择课程',exact=True).click()
        dialog.locator('.course-option input:checked').first.wait_for()
        assert dialog.locator('.course-picker section').count()==1
        assert dialog.locator('.course-option input:checked').count()==2
        page.set_viewport_size({'width':390,'height':844})
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(output/'mobile-wizard-courses.png'))
        page.keyboard.press('Escape')
        page.set_viewport_size({'width':1440,'height':1000})
        passed('账号卡片预选单个账号，第二步限定其课程，手机选择表单无溢出')
        # 单个账号读取失败仍显示具体提示，其他账号可以选择。
        page.get_by_role('button',name='新建学习任务',exact=True).click()
        dialog.wait_for()
        dialog.get_by_role('button',name='清除账号选择',exact=True).click()
        assert dialog.get_by_role('button',name='下一步：选择课程',exact=True).is_disabled()
        dialog.get_by_role('button',name='全选账号',exact=True).click()
        fail_id=next(iter(selected_ids))
        page.route(f'**/api/accounts/{fail_id}/courses',lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'detail':'课程读取暂时失败（验收）'},ensure_ascii=False)))
        dialog.get_by_role('button',name='下一步：选择课程',exact=True).click()
        dialog.get_by_text('课程读取失败：课程读取暂时失败（验收）。可重新读取或返回调整账号。',exact=True).wait_for()
        assert dialog.get_by_role('button',name='创建 0 项任务',exact=True).is_disabled()
        dialog.get_by_role('button',name='全选可学习课程',exact=True).click()
        assert dialog.locator('.course-option input:not(:disabled):checked').count()==12
        assert dialog.locator('.course-option input:disabled:checked').count()==0
        page.keyboard.press('Escape')
        page.unroute(f'**/api/accounts/{fail_id}/courses')
        passed('空账号禁止下一步，读取失败分账号提示，全选排除关闭课程')
        page.get_by_role('button',name='任务记录与历史',exact=True).click()
        page.get_by_label('任务状态').select_option('all')
        summary=page.locator('.task-live-summary').first
        summary.wait_for()
        page.wait_for_function('''() => Array.from(document.querySelectorAll(".task-live-summary")).some((el) => el.textContent.includes("预计剩余"))''')
        texts=[t for t in page.locator('.task-live-summary').all_inner_texts() if t]
        assert texts and all('预计剩余' in t for t in texts), ascii(texts)
        assert any(('正在' in t) or ('暂停' in t) for t in texts), ascii(texts)
        passed('任务列表运行中行显示当前动作与预计剩余时间')
        page.get_by_label('任务详情',exact=True).first.click()
        dialog.wait_for()
        page.get_by_role('button',name='诊断日志',exact=True).click()
        page.get_by_label('日志分类').select_option('llm')
        with page.expect_download() as download:
            page.get_by_role('link',name='下载完整日志').click()
        assert download.value.suggested_filename.endswith('.log')
        page.keyboard.press('Escape');assert dialog.count()==0
        passed('历史任务详情、诊断分类、完整日志下载与键盘关闭')
        page.get_by_label('打开站内通知栏').click()
        notice=page.get_by_role('region',name='站内通知栏');notice.wait_for()
        page.screenshot(path=str(output/'desktop-notices.png'))
        before=page.request.get(url+'/api/notifications?include_read=false').json()['unread']
        notice.get_by_label('处理这条通知').first.click()
        page.get_by_text('通知已标记处理',exact=True).wait_for()
        after=page.request.get(url+'/api/notifications?include_read=false').json()['unread']
        assert after==before-1
        page.keyboard.press('Escape');assert notice.count()==0
        passed('站内通知栏读取、标记处理与 Escape 关闭')
        nav.get_by_role('button',name='答题缓存').click()
        page.get_by_role('button',name='导入缓存',exact=True).click()
        page.get_by_label('缓存内容').fill(json.dumps([{'question_text':'Vue界面验收','answer':'A','options':['A.甲','B.乙'],'question_type':'单选题'}],ensure_ascii=False))
        page.get_by_role('button',name='检查并预览').click()
        page.get_by_text('已识别 1 道题',exact=False).wait_for()
        page.get_by_role('button',name='确认导入').click()
        page.wait_for_selector('.modal',state='detached')
        page.get_by_label('搜索答题缓存').fill('Vue界面验收')
        page.get_by_text('Vue界面验收',exact=True).wait_for()
        passed('答题缓存导入预览、确认与搜索')
        page.get_by_label('搜索答题缓存').fill('')
        page.get_by_role('button',name='清空全部',exact=True).click()
        page.get_by_role('button',name='确认清空全部',exact=True).click()
        page.wait_for_selector('.modal',state='detached')
        assert page.request.get(url+'/api/question-bank/stats').json()['total']==0
        passed('清空全部答题缓存需二次确认，清空后总量为 0')
        # 独立考试：加载列表、全选/取消全选、单选后按 selected 范围提交
        def catalog_route(route):
            exam='kind=exam' in route.request.url
            items=([{'id':'exam-a','title':'期末考试 A','status':'待做','start_time':'10/20 09:00',
                     'end_time':'10/20 11:00','limit_time':90,'valid':True},
                    {'id':'exam-b','title':'章节小测 B','status':'已完成','valid':False}] if exam else
                   [{'id':'hw-a','title':'第三章作业','status':'待做','time_left':'2 天','valid':True}])
            route.fulfill(status=200,content_type='application/json',body=json.dumps({
                'account_id':'','course_id':'','kind':'exam' if exam else 'work',
                'items':items,'fetched_at':time.time(),'from_cache':False,'error':''},ensure_ascii=False))
        catalog_pattern=re.compile(r'/api/accounts/[^/]+/courses/[^/]+/catalog')
        page.route(catalog_pattern,catalog_route)
        nav.get_by_role('button',name='学习任务').click()
        page.get_by_role('button',name='新建学习任务',exact=True).click()
        dialog.wait_for()
        dialog.get_by_role('button',name='清除账号选择',exact=True).click()
        dialog.locator('.wizard-account input').first.check()
        dialog.get_by_role('button',name='下一步：选择课程',exact=True).click()
        page.wait_for_function('document.querySelectorAll(".course-option").length>0')
        dialog.get_by_role('button',name='全选可学习课程',exact=True).click()
        page.wait_for_function('document.querySelectorAll(".course-option").length>0')
        dialog.get_by_role('button',name='独立考试',exact=True).click()
        dialog.get_by_role('button',name='加载考试列表',exact=False).click()
        page.locator('.catalog-item').first.wait_for()
        assert dialog.locator('.catalog-item input:checked').count()>=1
        # 2.2.1：考试说明页需要平台安全验证，列表提供说明与「在浏览器中打开」
        open_calls = []
        open_pattern = re.compile(r'/api/accounts/[^/]+/open-chaoxing$')
        def open_route(route):
            open_calls.append(route.request.post_data_json)
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'ok': True}))
        page.route(open_pattern, open_route)
        dialog.get_by_text('进入前可能需要平台安全验证', exact=False).first.wait_for()
        open_button = dialog.get_by_label('在浏览器中打开考试')
        assert open_button.count() >= 1
        open_button.first.click()
        page.get_by_text('已用浏览器打开考试说明页', exact=False).wait_for()
        assert open_calls, open_calls
        assert 'mooc1.chaoxing.com/exam/test/examcode/examnotes' in open_calls[-1]['url']
        assert 'examId=exam-a' in open_calls[-1]['url']
        page.unroute(open_pattern)
        passed('考试列表提示平台安全验证，并可用已保存会话在浏览器中打开说明页')
        dialog.get_by_role('button',name='全选考试',exact=False).click()
        assert dialog.locator('.catalog-item input:checked').count()==0
        dialog.locator('.catalog-item input:not(:disabled)').first.check()
        assert '已选 1' in dialog.inner_text()
        page.screenshot(path=str(output/'desktop-exam-selection.png'))
        # 2.2.2：粘贴带 enc 的答题页地址，按该地址逐题作答（平台验证由用户在浏览器完成）
        exam_url = ('https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew?'
                    'courseId=244694077&classId=151670988&tId=11021171&id=171477623&p=1&tag=1'
                    '&enc=b4acbaa84dfa579ce1c7884985a2eeee&cpi=518380181&newMooc=true')
        dialog.locator('.exam-url-input').fill(exam_url)
        page.screenshot(path=str(output/'desktop-exam-url.png'))
        passed('独立考试提供答题页地址输入框，可粘贴带 enc 的考试地址')
        with page.expect_response(lambda r:r.url.endswith('/api/runs') and r.request.method=='POST') as created:
            dialog.get_by_role('button',name=re.compile(r'创建 \d+ 项任务'),exact=False).click()
        payload=created.value.request.post_data_json
        assert payload['feature']=='exam'
        assert payload['params']['selection']['mode']=='selected'
        assert len(payload['params']['selection']['ids'])==1
        assert payload['params']['exam']['url']==exam_url
        page.wait_for_selector('.modal',state='detached')
        page.unroute(catalog_pattern)
        passed('独立考试可加载待做考试，默认全选、取消全选与单选后提交 selected 范围')
        nav.get_by_role('button',name='学习任务').click()
        page.get_by_role('button',name='任务记录与历史',exact=True).click()
        page.get_by_label('任务状态').select_option('paused')
        page.wait_for_timeout(300)
        # 独立考试任务：stage=exam 的运行文案，且老任务无逐题明细时给空状态
        page.locator('.task-row',has_text='中国近现代史纲要').filter(has_text='已暂停').first.get_by_label('任务详情',exact=True).click()
        dialog.wait_for()
        live_line=page.locator('.detail-live-line')
        live_line.get_by_text('AI 正在作答考试').wait_for()
        assert '已用时' in live_line.inner_text()
        verify_hint = page.locator('.detail-verify-hint')
        verify_hint.wait_for()
        assert '人工验证' in verify_hint.inner_text()
        assert '安全验证' in verify_hint.inner_text()
        page.screenshot(path=str(output/'desktop-exam-verify.png'))
        passed('考试任务详情提示需要人工验证且程序未启动考试')
        page.get_by_role('button',name='AI 做题',exact=False).click()
        page.locator('.answer-empty').wait_for()
        assert page.locator('.answer-card').count()==0
        page.keyboard.press('Escape')
        passed('独立考试任务详情显示 AI 正在作答考试与运行时长，无明细时给空状态')
        # 独立作业任务：逐题明细与来源摘要
        page.locator('.task-row',has_text='大学英语综合').filter(has_text='已暂停').first.get_by_label('任务详情',exact=True).click()
        dialog.wait_for()
        page.get_by_role('button',name='AI 做题',exact=False).click()
        page.wait_for_function('document.querySelectorAll(".answer-card").length>=4')
        assert page.locator('.answer-summary').count()==1
        assert page.get_by_text('未识别',exact=True).count()>=1
        page.screenshot(path=str(output/'desktop-ai-answers.png'))
        page.keyboard.press('Escape')
        assert dialog.count()==0
        passed('AI 做题明细按题渲染，摘要含来源分布且未识别题目标注原因')
        # 2.2.1：中断/停止/失败任务可继续执行（resume 用 route mock，避免依赖后端实现进度）
        resume_pattern = re.compile(r'/api/tasks/[^/]+/resume$')
        resume_calls = []
        def resume_route(route):
            resume_calls.append(route.request.url)
            route.fulfill(status=201, content_type='application/json',
                          body=json.dumps({'id': 'task-ui-resume', 'status': 'pending'}))
        page.get_by_label('任务状态').select_option('all')
        page.locator('.task-row', has_text='已中断').first.wait_for()
        page.route(resume_pattern, resume_route)
        interrupted_row = page.locator('.task-row', has_text='已中断').first
        assert interrupted_row.locator('.resume-action').count() == 1
        assert '项未完成' in interrupted_row.inner_text()
        interrupted_row.locator('.resume-action').click()
        page.get_by_text('已创建续跑任务', exact=True).wait_for()
        assert resume_calls and resume_calls[-1].endswith('/resume'), resume_calls
        passed('中断任务显示未完成项与继续执行按钮，点击后创建续跑任务')
        # 总览顶部提示条：上次任务未完成，共 N 项
        nav.get_by_role('button', name='工作总览').click()
        banner = page.locator('.resume-banner')
        banner.wait_for()
        assert '上次任务未完成，共' in banner.inner_text()
        banner.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        page.screenshot(path=str(output / 'desktop-resume.png'))
        passed('总览顶部提示上次任务未完成项数')
        # 课程任务点文案在「账号与课程」页的课程弹窗里，先切过去再断言
        nav.get_by_role('button', name='账号与课程').click()
        page.get_by_role('button', name='查看课程').first.click()
        course_dialog = page.get_by_role('dialog')
        course_dialog.wait_for()
        mission = course_dialog.locator('.course-mission').first
        mission.wait_for()
        assert '已完成' in mission.inner_text() and '/' in mission.inner_text(), mission.inner_text()
        page.screenshot(path=str(output / 'desktop-mission.png'))
        passed('课程任务点显示已完成 x / y 与待完成数量')
        page.get_by_role('button', name='关闭面板').click()
        nav.get_by_role('button', name='工作总览').click()
        banner = page.locator('.resume-banner')
        banner.wait_for()
        banner.get_by_role('button', name='继续执行', exact=True).click()
        page.get_by_text('已创建续跑任务', exact=True).wait_for()
        assert len(resume_calls) >= 2
        page.unroute(resume_pattern)
        passed('总览顶部提示上次任务未完成项数，可直接继续执行')

        nav.get_by_role('button',name='偏好设置').click()
        assert page.get_by_role('button',name='外部通知',exact=True).count()==0
        page.get_by_role('button',name='AI 服务',exact=True).click()
        page.get_by_label('模型名称',exact=True).fill('vue-validation-model')
        page.get_by_label('API Key',exact=True).fill('isolated-test-key')
        page.get_by_role('button',name='保存设置').click()
        page.get_by_text('设置已保存，后续创建的任务将使用新配置',exact=True).wait_for()
        assert page.get_by_label('API Key',exact=True).input_value()==''
        page.reload()
        page.get_by_role('button',name='AI 服务',exact=True).click()
        assert page.get_by_label('模型名称',exact=True).input_value()=='vue-validation-model'
        passed('取消外部通知设置、配置持久化、密钥保存后不回显')
        page.get_by_role('button', name='运行与存储', exact=True).click()
        sync_switch = page.get_by_label('启动时自动同步课程', exact=True)
        sync_switch.wait_for()
        assert sync_switch.is_checked()
        passed('偏好设置提供启动时自动同步课程开关且默认开启')

        from app import main
        for i in range(101):
            main.db.upsert_notification(category='font',title=f'分页验收 {i}',detail='测试通知',level='warning',dedupe_key=f'pagination-{i}')
        nav.get_by_role('button',name='问题中心').click()
        page.get_by_label('问题分类').select_option('font')
        page.get_by_role('button',name='下一页',exact=True).click()
        page.wait_for_function('document.querySelectorAll(".problem-card").length===1')
        page.get_by_label('标为已处理',exact=True).click()
        page.wait_for_function('document.querySelectorAll(".problem-card").length===100')
        passed('最后一页通知处理后回到有效页，其余通知仍可访问')
        win.get_by_role('button',name='关闭进度小窗').click()
        page.wait_for_function('document.querySelectorAll(".progress-window").length===0')
        passed('进度小窗可关闭，关闭后不再遮挡页面')
        browser.close()
    checks.append({'name':'浏览器没有运行错误','ok':not errors})
    report={'checks':checks,'errors':errors,'passed':sum(c['ok'] for c in checks)}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return all(c['ok'] for c in checks)

if __name__=='__main__':
    app,sandbox=prepare()
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    output=ROOT/'docs'/'vue-validation';output.mkdir(parents=True,exist_ok=True)
    try:ok=check(f'http://127.0.0.1:{port}',output)
    finally:server.should_exit=True;thread.join(timeout=10)
    sys.exit(0 if ok else 1)

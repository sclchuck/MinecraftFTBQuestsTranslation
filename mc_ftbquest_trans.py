from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

import wx
from openai import OpenAI
from key2lang import *


class JsonTranslateParallelGUI(wx.Frame):
    def __init__(self):
        super().__init__(parent=None, title='FTB Quests 汉化工具 v4.0', size=(1140, 860))

        self.num_threads = 3 
        self.SetBackgroundColour(wx.Colour(245, 245, 245))
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(panel, label='FTB Quests 抽取 + 并行翻译 + 回填 一体化工具 v4.0', style=wx.ALIGN_CENTER)
        title.SetFont(wx.Font(18, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        main_sizer.Add(title, 0, wx.ALL | wx.EXPAND, 15)

        path_box = wx.StaticBoxSizer(wx.StaticBox(panel, label='FTB Quests 路径'), wx.VERTICAL)
        path_grid = wx.FlexGridSizer(3, 2, 10, 10)
        path_grid.AddGrowableCol(1)

        self.quests_dir_ctrl = wx.TextCtrl(panel)
        browse_quests_btn = wx.Button(panel, label='选择 quests 文件夹')
        browse_quests_btn.Bind(wx.EVT_BUTTON, self.on_browse_quests_dir)
        hbox_quests = wx.BoxSizer(wx.HORIZONTAL)
        hbox_quests.Add(self.quests_dir_ctrl, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_quests.Add(browse_quests_btn, 0)
        path_grid.Add(wx.StaticText(panel, label='quests 路径:'), 0, wx.ALIGN_CENTER_VERTICAL)
        path_grid.Add(hbox_quests, 0, wx.EXPAND)

        self.input_file_ctrl = wx.TextCtrl(panel)
        path_grid.Add(wx.StaticText(panel, label='lang_original.json:'), 0, wx.ALIGN_CENTER_VERTICAL)
        path_grid.Add(self.input_file_ctrl, 0, wx.EXPAND)

        self.output_file_ctrl = wx.TextCtrl(panel)
        path_grid.Add(wx.StaticText(panel, label='lang_zh_cn.json:'), 0, wx.ALIGN_CENTER_VERTICAL)
        path_grid.Add(self.output_file_ctrl, 0, wx.EXPAND)

        path_box.Add(path_grid, 0, wx.ALL | wx.EXPAND, 12)
        main_sizer.Add(path_box, 0, wx.ALL | wx.EXPAND, 10)

        api_box = wx.StaticBoxSizer(wx.StaticBox(panel, label='API 配置'), wx.VERTICAL)
        grid = wx.FlexGridSizer(6, 2, 10, 10)
        grid.AddGrowableCol(1)

        self.base_url_ctrl = wx.TextCtrl(panel, value='https://dashscope.aliyuncs.com/compatible-mode/v1', size=(400, -1))
        grid.Add(wx.StaticText(panel, label='Base URL:'), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.base_url_ctrl, 0, wx.EXPAND)

        self.api_key_ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        grid.Add(wx.StaticText(panel, label='API Key:'), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.api_key_ctrl, 0, wx.EXPAND)

        self.model_ctrl = wx.TextCtrl(panel, value='qwen-mt-flash')
        grid.Add(wx.StaticText(panel, label='模型名称:'), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.model_ctrl, 0, wx.EXPAND)

        self.extra_prompt_ctrl = wx.TextCtrl(panel, value='')
        grid.Add(wx.StaticText(panel, label='额外提示词: '), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.extra_prompt_ctrl, 0, wx.EXPAND)

        self.num_threads_ctrl = wx.SpinCtrl(panel, value='3', min=1, max=25)
        grid.Add(wx.StaticText(panel, label='并行线程数 (推荐 2-4):'), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.num_threads_ctrl, 0)

        self.batch_size_ctrl = wx.SpinCtrl(panel, value='40', min=1, max=100)
        grid.Add(wx.StaticText(panel, label='每批条数:'), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.batch_size_ctrl, 0)

        api_box.Add(grid, 0, wx.ALL | wx.EXPAND, 12)
        main_sizer.Add(api_box, 0, wx.ALL | wx.EXPAND, 10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.prepare_btn = wx.Button(panel, label='📦 仅抽取', size=(120, 45))
        self.prepare_btn.Bind(wx.EVT_BUTTON, self.on_prepare_only)

        self.start_btn = wx.Button(panel, label='🚀 一键抽取+翻译+回填', size=(220, 45))
        self.start_btn.SetBackgroundColour(wx.Colour(0, 180, 0))
        self.start_btn.SetForegroundColour(wx.WHITE)
        self.start_btn.Bind(wx.EVT_BUTTON, self.on_start)

        self.backfill_btn = wx.Button(panel, label='📥 仅回填', size=(120, 45))
        self.backfill_btn.Bind(wx.EVT_BUTTON, self.on_backfill_only)

        self.stop_btn = wx.Button(panel, label='⏹ 停止', size=(120, 45))
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        self.stop_btn.Disable()

        self.clean_btn = wx.Button(panel, label='🧹 清理假翻译', size=(160, 45))
        self.clean_btn.SetBackgroundColour(wx.Colour(255, 140, 0))
        self.clean_btn.SetForegroundColour(wx.WHITE)
        self.clean_btn.Bind(wx.EVT_BUTTON, self.on_clean_fake)

        btn_sizer.Add(self.prepare_btn, 0, wx.ALL, 8)
        btn_sizer.Add(self.start_btn, 0, wx.ALL, 8)
        btn_sizer.Add(self.backfill_btn, 0, wx.ALL, 8)
        btn_sizer.Add(self.stop_btn, 0, wx.ALL, 8)
        btn_sizer.Add(self.clean_btn, 0, wx.ALL, 8)
        btn_sizer.AddStretchSpacer(1)
        main_sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        monitor_sizer = wx.BoxSizer(wx.HORIZONTAL)
        thread_box = wx.StaticBoxSizer(wx.StaticBox(panel, label='实时线程状态'), wx.VERTICAL)
        self.thread_status_text = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL, size=(-1, 180))
        self.thread_status_text.SetFont(wx.Font(10, wx.FONTFAMILY_MODERN, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        thread_box.Add(self.thread_status_text, 1, wx.ALL | wx.EXPAND, 8)
        monitor_sizer.Add(thread_box, 1, wx.ALL | wx.EXPAND, 10)

        log_box = wx.StaticBoxSizer(wx.StaticBox(panel, label='运行日志'), wx.VERTICAL)
        self.log_text = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2, size=(-1, 180))
        log_box.Add(self.log_text, 1, wx.ALL | wx.EXPAND, 8)
        monitor_sizer.Add(log_box, 3, wx.ALL | wx.EXPAND, 10)
        main_sizer.Add(monitor_sizer, 1, wx.EXPAND)

        self.progress = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        main_sizer.Add(self.progress, 0, wx.ALL | wx.EXPAND, 12)

        panel.SetSizer(main_sizer)
        self.Show()

        self.is_running = False
        self.threads_status: Dict[str, str] = {}
        self.lock = threading.Lock()
        self.translated_data: Dict[str, str] = {}
        self.total = 0
        self.processed = 0
        self.original: Dict[str, str] = {}
        self.packer: FTBQuestLangPacker | None = None
        self.status_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_thread_status, self.status_timer)

        self.log('✅ v4.0 已就绪！已改为文本式 SNBT 处理，不再依赖 nbtlib。', wx.BLUE)

    def log(self, msg: str, color=wx.BLACK):
        wx.CallAfter(self._log, msg, color)

    def _log(self, msg: str, color):
        self.log_text.SetDefaultStyle(wx.TextAttr(color))
        self.log_text.AppendText(f"{time.strftime('%H:%M:%S')}  {msg}\n")

    def on_browse_quests_dir(self, event):
        dlg = wx.DirDialog(self, '选择 FTB Quests 的 quests 文件夹', style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            quests_dir = dlg.GetPath()
            self.quests_dir_ctrl.SetValue(quests_dir)
            self.refresh_work_paths(quests_dir)
        dlg.Destroy()

    def refresh_work_paths(self, quests_dir: str):
        try:
            self.packer = FTBQuestLangPacker(quests_dir)
            self.input_file_ctrl.SetValue(str(self.packer.lang_original_path))
            self.output_file_ctrl.SetValue(str(self.packer.lang_zh_cn_path))
            self.log(f'工作目录已设置: {self.packer.work_dir}', wx.BLUE)
        except Exception as e:
            self.packer = None
            self.log(f'路径初始化失败: {e}', wx.RED)

    def require_packer(self) -> FTBQuestLangPacker | None:
        quests_dir = self.quests_dir_ctrl.GetValue().strip()
        if not quests_dir:
            wx.MessageBox('请先选择 quests 文件夹。', '提示', wx.OK | wx.ICON_INFORMATION)
            return None
        if self.packer is None or str(self.packer.quests_dir) != str(Path(quests_dir).resolve()):
            self.refresh_work_paths(quests_dir)
        return self.packer

    def set_running_state(self, running: bool):
        self.is_running = running
        if running:
            self.start_btn.Disable()
            self.prepare_btn.Disable()
            self.backfill_btn.Disable()
            self.stop_btn.Enable()
        else:
            self.start_btn.Enable()
            self.prepare_btn.Enable()
            self.backfill_btn.Enable()
            self.stop_btn.Disable()

    def on_prepare_only(self, event):
        if self.is_running:
            return
        packer = self.require_packer()
        if packer is None:
            return
        try:
            lang_map = packer.extract_all(clear_output=True)
            self.original = lang_map
            self.input_file_ctrl.SetValue(str(packer.lang_original_path))
            self.output_file_ctrl.SetValue(str(packer.lang_zh_cn_path))
            wx.MessageBox(
                f'抽取完成！\n共提取 {len(lang_map)} 条文本。\n\n已生成:\n- {packer.lang_original_path}\n- {packer.lang_key_dir}',
                '成功',
                wx.OK | wx.ICON_INFORMATION,
            )
            self.log(f'📦 抽取完成，共 {len(lang_map)} 条', wx.GREEN)
        except Exception as e:
            wx.MessageBox(str(e), '错误', wx.OK | wx.ICON_ERROR)
            self.log(f'抽取失败: {e}', wx.RED)

    def on_backfill_only(self, event):
        if self.is_running:
            return
        packer = self.require_packer()
        if packer is None:
            return
        try:
            packer.backfill_all(clear_output=True, fallback_to_original=True)
            wx.MessageBox(
                f'回填完成！\n输出目录:\n{packer.translated_dir}',
                '成功',
                wx.OK | wx.ICON_INFORMATION,
            )
            self.log(f'📥 回填完成: {packer.translated_dir}', wx.GREEN)
        except Exception as e:
            wx.MessageBox(str(e), '错误', wx.OK | wx.ICON_ERROR)
            self.log(f'回填失败: {e}', wx.RED)

    def on_start(self, event):
        if self.is_running:
            return

        packer = self.require_packer()
        if packer is None:
            return

        base_url = self.base_url_ctrl.GetValue().strip()
        api_key = self.api_key_ctrl.GetValue().strip()
        model = self.model_ctrl.GetValue().strip()
        num_threads = self.num_threads_ctrl.GetValue()
        batch_size = self.batch_size_ctrl.GetValue()

        if not all([api_key, model]):
            wx.MessageBox('请填写 API Key 和模型名称！', '错误', wx.OK | wx.ICON_ERROR)
            return

        self.thread_status_text.Clear()
        self.threads_status = {}
        self.set_running_state(True)

        threading.Thread(
            target=self.run_full_pipeline,
            args=(packer, base_url, api_key, model, num_threads, batch_size),
            daemon=True,
        ).start()

    def run_full_pipeline(self, packer: FTBQuestLangPacker, base_url: str, api_key: str, model: str, num_threads: int, batch_size: int):
        try:
            self.log('📦 开始抽取 SNBT 文本...', wx.BLUE)
            self.original = packer.extract_all(clear_output=True)
            self.input_file_ctrl.SetValue(str(packer.lang_original_path))
            self.output_file_ctrl.SetValue(str(packer.lang_zh_cn_path))
            self.log(f'抽取完成，共 {len(self.original)} 条', wx.GREEN)

            self.log('🌐 开始多线程翻译...', wx.BLUE)
            self.run_parallel_translation(
                base_url=base_url,
                api_key=api_key,
                model=model,
                num_threads=num_threads,
                batch_size=batch_size,
                input_file=str(packer.lang_original_path),
                output_file=str(packer.lang_zh_cn_path),
            )

            if not self.is_running:
                self.log('流程已停止，跳过回填。', wx.Colour(255, 140, 0))
                return

            self.log('📥 开始回填翻译结果...', wx.BLUE)
            packer.backfill_all(clear_output=True, fallback_to_original=True)
            self.log(f'回填完成，输出目录: {packer.translated_dir}', wx.GREEN)
            wx.CallAfter(
                wx.MessageBox,
                f'全部完成！\n\n工作目录:\n{packer.work_dir}\n\n输出目录:\n{packer.translated_dir}',
                '成功',
                wx.OK | wx.ICON_INFORMATION,
            )
        except Exception as e:
            self.log(f'严重错误: {e}', wx.RED)
        finally:
            wx.CallAfter(self.status_timer.Stop)
            wx.CallAfter(self.finish)

    def update_thread_status(self, event=None):
        """线程状态实时更新（已修复）"""
        if not self.is_running:
            return
        with self.lock:
            lines = [f'活跃线程: {len(self.threads_status)} / {self.num_threads}']
            for tname, info in sorted(self.threads_status.items()):
                lines.append(f'  {tname}: {info}')
        self.thread_status_text.SetValue('\n'.join(lines))

    def run_parallel_translation(self, base_url: str, api_key: str, model: str, num_threads: int, batch_size: int, input_file: str, output_file: str):
        client = OpenAI(base_url=base_url, api_key=api_key)

        system_prompt = """你是一个专业的 Minecraft 模组 + FTB Quests 中文化专家。

翻译规则（必须严格遵守）：
1. 只翻译 JSON 的 VALUE，KEY 必须 100% 原样不动。
2. 所有专有名词尽量翻译准确，必要时保留英文原名在括号中。
3. 所有颜色代码必须完整保留（如 &6、&a、&9、&r、&l 等），不要修改、删除或翻译。
4. 翻译要自然流畅，像官方汉化一样好读。
5. 空字符串必须保留为空字符串。
6. 只返回一个有效的 JSON 对象，不要有任何额外文字、解释、markdown。"""

        with open(input_file, 'r', encoding='utf-8') as f:
            self.original = json.load(f)

        current_index_file = os.path.join(os.path.dirname(input_file), "lang_index.json")

        if os.path.exists(output_file):
            with open(output_file, 'r', encoding='utf-8') as f:
                loaded_translated = json.load(f)

            self.translated_data = self.remap_translated_by_current_index(
                original_map=self.original,
                translated_map=loaded_translated,
                index_path=current_index_file,
            )

            self.log(f'断点续传：已复用 {len(self.translated_data)} 条', wx.GREEN)
        else:
            self.translated_data = {}

        remaining = {k: v for k, v in self.original.items() if k not in self.translated_data}

        self.total = len(self.original)
        self.processed = len(self.translated_data)

        self.log(
            f'总条数 {len(self.original)} | 已复用 {len(self.translated_data)} | 剩余待翻译 {len(remaining)}',
            wx.BLUE
        )

        wx.CallAfter(self.progress.SetRange, max(1, self.total))
        wx.CallAfter(self.progress.SetValue, self.processed)

        if not remaining:
            self.log('🎉 lang_zh_cn.json 已全部完成，无需重复翻译。', wx.GREEN)
            return

        items_list = list(remaining.items())
        chunk_size = max(1, (len(items_list) + num_threads - 1) // num_threads)
        chunks = [items_list[i:i + chunk_size] for i in range(0, len(items_list), chunk_size)]
        self.num_threads = num_threads
        wx.CallAfter(self.status_timer.Start, 800)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            future_to_name = {}
            for idx, chunk in enumerate(chunks):
                thread_name = f'Thread-{idx + 1:02d}'
                future = executor.submit(
                    self.process_chunk,
                    thread_name,
                    chunk,
                    client,
                    model,
                    system_prompt,
                    batch_size,
                    output_file,
                )
                future_to_name[future] = thread_name

            for future in as_completed(future_to_name):
                if not self.is_running:
                    break
                try:
                    future.result()
                except Exception as e:
                    self.log(f'{future_to_name[future]} 出错: {e}', wx.RED)

        if self.processed >= self.total:
            self.log(f'🎉 并行汉化全部完成！共 {len(self.translated_data)} 条', wx.GREEN)

    def process_chunk(self, thread_name: str, chunk: List[Tuple[str, str]], client: OpenAI, model: str, system_prompt: str, batch_size: int, output_file: str):
        chunk_processed = 0
        total_in_chunk = len(chunk)

        for i in range(0, len(chunk), batch_size):
            if not self.is_running:
                break

            batch = dict(chunk[i:i + batch_size])
            batch_start = i
            batch_end = min(i + batch_size, len(chunk))

            with self.lock:
                self.threads_status[thread_name] = (
                    f'范围 {batch_start}-{batch_end} | 进度 {chunk_processed}/{total_in_chunk}'
                )
                wx.CallAfter(self.update_thread_status)   # ← 主动实时刷新

            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{
                        'role': 'user',
                        'content': f"{system_prompt}\n{self.extra_prompt_ctrl.GetValue().strip()}\n\n请翻译以下 JSON（只翻译 value）：\n{json.dumps(batch, ensure_ascii=False, separators=(',', ':'))}"
                    }],
                    temperature=0.15,
                    response_format={'type': 'json_object'},
                )
                translated_batch = json.loads(response.choices[0].message.content)

                with self.lock:
                    self.translated_data.update(translated_batch)
                    self.processed = len(self.translated_data)
                    chunk_processed += len(translated_batch)
                    ordered_data = {k: self.translated_data[k] for k in self.original if k in self.translated_data}
                    with open(output_file, 'w', encoding='utf-8', newline='\n') as f:
                        json.dump(ordered_data, f, ensure_ascii=False, indent=2)

                    self.threads_status[thread_name] = f'已完成 ({chunk_processed}/{total_in_chunk})'
                    wx.CallAfter(self.update_thread_status)   # ← 再次主动刷新

                wx.CallAfter(self.progress.SetValue, min(self.processed, self.total))
                self.log(f'{thread_name} 完成一批 ({len(translated_batch)} 条)', wx.BLACK)

            except Exception as e:
                self.log(f'{thread_name} 批次失败: {e}', wx.RED)
                time.sleep(2)

        with self.lock:
            self.threads_status[thread_name] = f'✅ 已完成 ({chunk_processed}/{total_in_chunk})'
            wx.CallAfter(self.update_thread_status)

    def on_stop(self, event):
        self.is_running = False
        self.log('⏹ 用户请求停止，正在等待当前批次结束。', wx.Colour(255, 140, 0))

    def finish(self):
        self.set_running_state(False)
        self.progress.SetValue(0)
        self.log('任务结束。', wx.BLUE)

    def on_clean_fake(self, event):
        output_file = self.output_file_ctrl.GetValue().strip()
        if not output_file or not os.path.exists(output_file):
            wx.MessageBox('找不到 lang_zh_cn.json 文件！', '错误', wx.OK | wx.ICON_ERROR)
            return

        with open(output_file, 'r', encoding='utf-8') as f:
            translated = json.load(f)

        if not self.original:
            input_file = self.input_file_ctrl.GetValue().strip()
            if input_file and os.path.exists(input_file):
                with open(input_file, 'r', encoding='utf-8') as f:
                    self.original = json.load(f)
            else:
                wx.MessageBox('请先选择 quests 文件夹或先完成抽取。', '提示', wx.OK | wx.ICON_INFORMATION)
                return

        cleaned = 0
        chinese_pattern = re.compile(r'[\u4e00-\u9fff]')

        for k in list(translated.keys()):
            val = translated[k]
            if isinstance(val, str) and val and not chinese_pattern.search(val):
                del translated[k]
                cleaned += 1

        ordered = {k: translated[k] for k in self.original if k in translated}
        with open(output_file, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(ordered, f, ensure_ascii=False, indent=2)

        wx.MessageBox(
            f'清理完成！\n已移除 {cleaned} 条纯英文假翻译。\n\n这些条目下次运行会重新翻译。',
            '成功',
            wx.OK | wx.ICON_INFORMATION,
        )
        self.log(f'🧹 已清理 {cleaned} 条假翻译', wx.Colour(255, 140, 0))
    def load_json_safe(self, path: str) -> dict:
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.log(f'读取 JSON 失败 {path}: {e}', wx.RED)
            return {}


    def build_anchor_from_index_item(self, item: dict) -> str:
        """
        用 lang_index.json 中的位置信息构造稳定锚点。
        不依赖 key 本身，而依赖：
        - ids
        - field
        - list_index
        """
        ids = item.get("ids", []) or []
        field = item.get("field", "") or ""
        list_index = item.get("list_index", None)

        parts = []

        if ids:
            parts.append("/".join(str(x) for x in ids))
        else:
            parts.append(str(item.get("file", "") or ""))

        parts.append(str(field))

        if list_index is not None:
            parts.append(str(list_index))

        return "|".join(parts)


    def remap_translated_by_current_index(
        self,
        original_map: dict,
        translated_map: dict,
        index_path: str,
    ) -> dict:
        """
        只使用当前 lang_index.json 做位置匹配复用：
        - 若新 key 直接存在于 zh_cn.json，直接复用
        - 否则根据当前 index 的 anchor，在 zh_cn.json 中寻找“同 anchor 的旧 key”对应翻译
        """
        index_data = self.load_json_safe(index_path)
        if not index_data:
            direct_only = {k: v for k, v in translated_map.items() if k in original_map}
            self.log(
                f'缺少 lang_index.json，仅按 key 直接命中复用 {len(direct_only)} 条',
                wx.BLUE
            )
            return direct_only

        # 当前 index: key -> anchor
        key_to_anchor = {}
        anchor_to_keys = {}

        for key, meta in index_data.items():
            if not isinstance(meta, dict):
                continue
            anchor = self.build_anchor_from_index_item(meta)
            if not anchor:
                continue
            key_to_anchor[key] = anchor
            anchor_to_keys.setdefault(anchor, []).append(key)

        remapped = {}

        direct_hits = 0
        anchor_hits = 0

        # 1. 先保留“当前 key 直接存在于 zh_cn.json” 的
        for k, v in translated_map.items():
            if k in original_map:
                remapped[k] = v
                direct_hits += 1

        # 2. 对 original_map 里的每个新 key，尝试按同 anchor 找已翻译 key
        for new_key in original_map:
            if new_key in remapped:
                continue

            anchor = key_to_anchor.get(new_key)
            if not anchor:
                continue

            candidate_keys = anchor_to_keys.get(anchor, [])
            for old_like_key in candidate_keys:
                if old_like_key in translated_map:
                    remapped[new_key] = translated_map[old_like_key]
                    anchor_hits += 1
                    break

        self.log(
            f'翻译复用完成：直接命中 {direct_hits} 条，位置锚点命中 {anchor_hits} 条，最终复用 {len(remapped)} 条',
            wx.BLUE
        )
        return remapped

if __name__ == '__main__':
    app = wx.App(False)
    frame = JsonTranslateParallelGUI()
    app.MainLoop()

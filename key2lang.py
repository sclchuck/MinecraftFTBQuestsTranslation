from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import json
import shutil


# =========================================================
# AST
# =========================================================

@dataclass
class Scalar:
	raw: str
	value: Any
	kind: str  # string / number / bool / bare


@dataclass
class KV:
	key: str
	value: Any


@dataclass
class Compound:
	items: List[KV] = field(default_factory=list)


@dataclass
class ListTag:
	items: List[Any] = field(default_factory=list)


# =========================================================
# Token-less FTB SNBT Parser
# 目标：兼容 FTB Quests/KubeJS 风格的“无逗号 SNBT”
# 不是完整 Mojangson，但足够处理 quests 配置
# =========================================================

class _FTBSnbtParser:
	def __init__(self, text: str):
		self.text = text
		self.n = len(text)
		self.i = 0

	def parse_document(self) -> List[Any]:
		roots = []
		self._ws()
		while self.i < self.n:
			roots.append(self._parse_value())
			self._ws()
		return roots

	def _peek(self) -> str:
		return self.text[self.i] if self.i < self.n else ""

	def _next(self) -> str:
		ch = self.text[self.i]
		self.i += 1
		return ch

	def _ws(self) -> None:
		while self.i < self.n:
			ch = self.text[self.i]
			if ch in " \t\r\n":
				self.i += 1
				continue
			# 支持 // 注释
			if ch == "/" and self.i + 1 < self.n and self.text[self.i + 1] == "/":
				self.i += 2
				while self.i < self.n and self.text[self.i] != "\n":
					self.i += 1
				continue
			# 支持 # 注释
			if ch == "#":
				self.i += 1
				while self.i < self.n and self.text[self.i] != "\n":
					self.i += 1
				continue
			break

	def _parse_value(self) -> Any:
		self._ws()
		ch = self._peek()
		if ch == "{":
			return self._parse_compound()
		if ch == "[":
			return self._parse_list()
		if ch == '"':
			return self._parse_string()
		return self._parse_scalar()

	def _parse_compound(self) -> Compound:
		if self._next() != "{":
			raise ValueError(f"Expected '{{' at {self.i}")
		items: List[KV] = []
		self._ws()
		while self.i < self.n and self._peek() != "}":
			key = self._parse_key()
			self._ws()
			if self._peek() != ":":
				raise ValueError(f"Expected ':' after key '{key}' at {self.i}")
			self.i += 1
			self._ws()
			value = self._parse_value()
			items.append(KV(key, value))
			self._ws()
			# FTB SNBT 可无逗号，也兼容有逗号
			if self._peek() == ",":
				self.i += 1
				self._ws()
		if self._peek() != "}":
			raise ValueError(f"Expected '}}' at {self.i}")
		self.i += 1
		return Compound(items)

	def _parse_list(self) -> ListTag:
		if self._next() != "[":
			raise ValueError(f"Expected '[' at {self.i}")
		items: List[Any] = []
		self._ws()
		while self.i < self.n and self._peek() != "]":
			item = self._parse_value()
			items.append(item)
			self._ws()
			# 兼容逗号，但不要求
			if self._peek() == ",":
				self.i += 1
				self._ws()
		if self._peek() != "]":
			raise ValueError(f"Expected ']' at {self.i}")
		self.i += 1
		return ListTag(items)

	def _parse_key(self) -> str:
		self._ws()
		ch = self._peek()
		if ch == '"':
			s = self._parse_string()
			return s.value

		start = self.i
		while self.i < self.n:
			ch = self.text[self.i]
			if ch in " \t\r\n:":
				break
			if ch in "{}[],":
				break
			self.i += 1
		if start == self.i:
			raise ValueError(f"Expected key at {self.i}")
		return self.text[start:self.i]

	def _parse_string(self) -> Scalar:
		if self._next() != '"':
			raise ValueError(f'Expected \'"\' at {self.i}')
		out = []
		raw = ['"']
		escape = False
		while self.i < self.n:
			ch = self._next()
			raw.append(ch)
			if escape:
				# 保持常见转义
				if ch == "n":
					out.append("\n")
				elif ch == "t":
					out.append("\t")
				elif ch == "r":
					out.append("\r")
				else:
					out.append(ch)
				escape = False
				continue
			if ch == "\\":
				escape = True
				continue
			if ch == '"':
				return Scalar("".join(raw), "".join(out), "string")
			out.append(ch)
		raise ValueError("Unterminated string")

	def _parse_scalar(self) -> Scalar:
		start = self.i
		while self.i < self.n:
			ch = self.text[self.i]
			if ch in " \t\r\n,]}":
				break
			self.i += 1
		raw = self.text[start:self.i]
		if raw == "":
			raise ValueError(f"Unexpected token at {self.i}")

		low = raw.lower()
		if low == "true":
			return Scalar(raw, True, "bool")
		if low == "false":
			return Scalar(raw, False, "bool")

		# number / number suffix
		if self._looks_like_number(raw):
			return Scalar(raw, raw, "number")

		return Scalar(raw, raw, "bare")

	@staticmethod
	def _looks_like_number(s: str) -> bool:
		# 支持 1 1.2 1.2d 3b 4s 5l 6f
		if not s:
			return False
		body = s[:-1] if s[-1] in "bBsSlLfFdD" else s
		if body.startswith("-"):
			body = body[1:]
		if not body:
			return False
		dot_count = body.count(".")
		if dot_count > 1:
			return False
		return all(ch.isdigit() or ch == "." for ch in body)


# =========================================================
# Serializer
# =========================================================

class _FTBSnbtSerializer:
	def __init__(self, indent: int = 4):
		self.indent = indent

	def dumps_document(self, roots: List[Any]) -> str:
		parts = [self.dumps(v, 0) for v in roots]
		return "\n".join(parts) + "\n"

	def dumps(self, node: Any, level: int = 0) -> str:
		if isinstance(node, Compound):
			return self._dump_compound(node, level)
		if isinstance(node, ListTag):
			return self._dump_list(node, level)
		if isinstance(node, Scalar):
			return node.raw if node.kind != "string" else self._quote(node.value)
		if isinstance(node, str):
			return self._quote(node)
		if isinstance(node, bool):
			return "true" if node else "false"
		return str(node)

	def _dump_compound(self, node: Compound, level: int) -> str:
		if not node.items:
			return "{}"
		pad = " " * (self.indent * level)
		pad_in = " " * (self.indent * (level + 1))
		lines = ["{"]
		for kv in node.items:
			lines.append(f"{pad_in}{kv.key}: {self.dumps(kv.value, level + 1)}")
		lines.append(f"{pad}}}")
		return "\n".join(lines)

	def _dump_list(self, node: ListTag, level: int) -> str:
		if not node.items:
			return "[]"

		simple = all(isinstance(x, Scalar) and x.kind == "string" for x in node.items)
		if simple:
			inner = "\n".join(
				(" " * (self.indent * (level + 1))) + self.dumps(x, level + 1)
				for x in node.items
			)
			return "[\n" + inner + "\n" + (" " * (self.indent * level)) + "]"

		pad = " " * (self.indent * level)
		pad_in = " " * (self.indent * (level + 1))
		lines = ["["]
		for item in node.items:
			rendered = self.dumps(item, level + 1)
			if "\n" in rendered:
				rendered_lines = rendered.splitlines()
				lines.append(pad_in + rendered_lines[0])
				for ln in rendered_lines[1:]:
					lines.append(pad_in + ln)
			else:
				lines.append(f"{pad_in}{rendered}")
		lines.append(f"{pad}]")
		return "\n".join(lines)

	@staticmethod
	def _quote(s: str) -> str:
		s = s.replace("\\", "\\\\")
		s = s.replace('"', '\\"')
		s = s.replace("\n", "\\n")
		s = s.replace("\t", "\\t")
		s = s.replace("\r", "\\r")
		return f'"{s}"'


# =========================================================
# Main packer
# =========================================================

class FTBQuestLangPacker:
	"""
	只处理 FTB Quests 的 SNBT 提取 / 回填。

	工作目录:
		{quests_dir}/../ftb_trans

	输出:
		lang_original.json
		lang_index.json
		ftbquests_lang_key/
		ftbquests_translated/
	"""

	TRANSLATABLE_FIELDS = {"title", "subtitle", "description", "name", "text"}

	def __init__(self, quests_dir: str | Path):
		self.quests_dir = Path(quests_dir).resolve()
		if not self.quests_dir.exists():
			raise FileNotFoundError(f"quests_dir 不存在: {self.quests_dir}")

		self.work_dir = self.quests_dir.parent / "ftb_trans"
		self.lang_original_path = self.work_dir / "lang_original.json"
		self.lang_index_path = self.work_dir / "lang_index.json"
		self.lang_zh_cn_path = self.work_dir / "lang_zh_cn.json"
		self.lang_key_dir = self.work_dir / "ftbquests_lang_key"
		self.translated_dir = self.work_dir / "ftbquests_translated"

		self.work_dir.mkdir(parents=True, exist_ok=True)
		self.lang_key_dir.mkdir(parents=True, exist_ok=True)
		self.translated_dir.mkdir(parents=True, exist_ok=True)

		self._serializer = _FTBSnbtSerializer(indent=4)

	# -----------------------------------------------------
	# Public API
	# -----------------------------------------------------

	def extract_all(self, clear_output: bool = True) -> Dict[str, str]:
		if clear_output:
			self._reset_dir(self.lang_key_dir)

		lang_map: Dict[str, str] = {}
		index_map: Dict[str, Dict[str, Any]] = {}

		snbt_files = sorted(self.quests_dir.rglob("*.snbt"))
		if not snbt_files:
			raise FileNotFoundError(f"未找到 .snbt 文件: {self.quests_dir}")

		for snbt_path in snbt_files:
			rel_path = snbt_path.relative_to(self.quests_dir)
			roots = self._load_snbt_document(snbt_path)

			# 提取并替换
			new_roots = []
			for root_idx, root in enumerate(roots):
				context = {
					"file": rel_path.as_posix(),
					"root_index": root_idx,
					"id_stack": [],
				}
				new_root = self._extract_node(
					node=root,
					context=context,
					field_name=None,
					field_index=None,
					lang_map=lang_map,
					index_map=index_map,
				)
				new_roots.append(new_root)

			out_path = self.lang_key_dir / rel_path
			out_path.parent.mkdir(parents=True, exist_ok=True)
			self._save_snbt_document(out_path, new_roots)

		self._save_json(self.lang_original_path, lang_map)
		self._save_json(self.lang_index_path, index_map)
		return lang_map

	def backfill_all(self, clear_output: bool = True, fallback_to_original: bool = True) -> None:
		if not self.lang_zh_cn_path.exists():
			raise FileNotFoundError(f"缺少翻译文件: {self.lang_zh_cn_path}")
		if not self.lang_original_path.exists():
			raise FileNotFoundError(f"缺少原文文件: {self.lang_original_path}")

		translated_map = self._load_json(self.lang_zh_cn_path)
		original_map = self._load_json(self.lang_original_path)

		if clear_output:
			self._reset_dir(self.translated_dir)

		snbt_files = sorted(self.lang_key_dir.rglob("*.snbt"))
		if not snbt_files:
			raise FileNotFoundError(f"未找到占位 SNBT: {self.lang_key_dir}")

		for snbt_path in snbt_files:
			rel_path = snbt_path.relative_to(self.lang_key_dir)
			roots = self._load_snbt_document(snbt_path)
			new_roots = [self._backfill_node(x, translated_map, original_map, fallback_to_original) for x in roots]

			out_path = self.translated_dir / rel_path
			out_path.parent.mkdir(parents=True, exist_ok=True)
			self._save_snbt_document(out_path, new_roots)

	def run_prepare(self) -> None:
		self.extract_all(clear_output=True)

	def run_backfill(self) -> None:
		self.backfill_all(clear_output=True, fallback_to_original=True)

	# -----------------------------------------------------
	# Extraction
	# -----------------------------------------------------

	def _extract_node(
		self,
		node: Any,
		context: Dict[str, Any],
		field_name: Optional[str],
		field_index: Optional[int],
		lang_map: Dict[str, str],
		index_map: Dict[str, Dict[str, Any]],
	) -> Any:
		if isinstance(node, Compound):
			obj_id = self._get_compound_id(node)

			# 压栈稳定 id
			pushed = False
			if obj_id:
				context = {
					**context,
					"id_stack": context["id_stack"] + [obj_id]
				}
				pushed = True

			new_items: List[KV] = []
			for kv in node.items:
				k = kv.key
				v = kv.value

				if k in self.TRANSLATABLE_FIELDS:
					new_v = self._extract_translatable_value(
						value=v,
						context=context,
						field_name=k,
						lang_map=lang_map,
						index_map=index_map,
					)
				else:
					new_v = self._extract_node(
						node=v,
						context=context,
						field_name=k,
						field_index=None,
						lang_map=lang_map,
						index_map=index_map,
					)
				new_items.append(KV(k, new_v))
			return Compound(new_items)

		if isinstance(node, ListTag):
			new_items = []
			for idx, item in enumerate(node.items):
				new_items.append(
					self._extract_node(
						node=item,
						context=context,
						field_name=field_name,
						field_index=idx,
						lang_map=lang_map,
						index_map=index_map,
					)
				)
			return ListTag(new_items)

		return node

	def _extract_translatable_value(
		self,
		value: Any,
		context: Dict[str, Any],
		field_name: str,
		lang_map: Dict[str, str],
		index_map: Dict[str, Dict[str, Any]],
	) -> Any:
		# 纯字符串字段
		if isinstance(value, Scalar) and value.kind == "string":
			if self._should_extract_text(value.value):
				key = self._build_stable_key(
					context=context,
					field_name=field_name,
					list_index=None,
					original_text=value.value,
				)
				lang_map.setdefault(key, value.value)
				index_map.setdefault(key, {
					"file": context["file"],
					"field": field_name,
					"ids": list(context["id_stack"]),
					"list_index": None,
				})
				return Scalar(raw=f'"{key}"', value=key, kind="string")
			return value

		# 字符串数组
		if isinstance(value, ListTag):
			new_items = []
			for idx, item in enumerate(value.items):
				if isinstance(item, Scalar) and item.kind == "string" and self._should_extract_text(item.value):
					key = self._build_stable_key(
						context=context,
						field_name=field_name,
						list_index=idx,
						original_text=item.value,
					)
					lang_map.setdefault(key, item.value)
					index_map.setdefault(key, {
						"file": context["file"],
						"field": field_name,
						"ids": list(context["id_stack"]),
						"list_index": idx,
					})
					new_items.append(Scalar(raw=f'"{key}"', value=key, kind="string"))
				else:
					new_items.append(
						self._extract_node(
							node=item,
							context=context,
							field_name=field_name,
							field_index=idx,
							lang_map=lang_map,
							index_map=index_map,
						)
					)
			return ListTag(new_items)

		# 极少数情况下可翻译字段里可能嵌套 compound/list
		return self._extract_node(
			node=value,
			context=context,
			field_name=field_name,
			field_index=None,
			lang_map=lang_map,
			index_map=index_map,
		)

	# -----------------------------------------------------
	# Backfill
	# -----------------------------------------------------

	def _backfill_node(
		self,
		node: Any,
		translated_map: Dict[str, str],
		original_map: Dict[str, str],
		fallback_to_original: bool = True,
	) -> Any:
		if isinstance(node, Compound):
			return Compound([
				KV(kv.key, self._backfill_node(kv.value, translated_map, original_map, fallback_to_original))
				for kv in node.items
			])

		if isinstance(node, ListTag):
			return ListTag([
				self._backfill_node(x, translated_map, original_map, fallback_to_original)
				for x in node.items
			])

		if isinstance(node, Scalar) and node.kind == "string" and self._is_generated_key(node.value):
			key = node.value
			if key in translated_map and isinstance(translated_map[key], str):
				val = translated_map[key]
				return Scalar(raw=f'"{self._escape_string(val)}"', value=val, kind="string")
			if fallback_to_original and key in original_map:
				val = original_map[key]
				return Scalar(raw=f'"{self._escape_string(val)}"', value=val, kind="string")
			return node

		return node

	# -----------------------------------------------------
	# Key Strategy
	# -----------------------------------------------------

	def _build_stable_key(
	  self,
	  context: Dict[str, Any],
	  field_name: str,
	  list_index: Optional[int],
	  original_text: str,
  ) -> str:
		"""
		【已改为明文 key】方便增量更新和调试
		示例: ftbquests.auto.quest_main.title.0.主线任务标题
		"""
		id_stack = context.get("id_stack", [])
		root_index = context.get("root_index", 0)

		if id_stack:
			anchor = ".".join(str(x) for x in id_stack)
		else:
			file_part = context["file"].replace("/", ".").replace("\\", ".").replace(" ", "_")
			anchor = f"{file_part}_root{root_index}"

		# 基础结构路径
		key = f"ftbquests.auto.{anchor}.{field_name}"
		if list_index is not None:
			key += f".{list_index}"

		# 原文简短预览（明文、可读，不用 hash）
		if original_text:
			snippet = "".join(c for c in original_text[:12] if c.isalnum() or c in "_-").strip("_")
			if snippet and len(snippet) >= 2:
				key += f".{snippet}"

		return key

	@staticmethod
	def _is_generated_key(s: str) -> bool:
		return s.startswith("ftbquests.auto.")

	# -----------------------------------------------------
	# Helpers
	# -----------------------------------------------------

	@staticmethod
	def _get_compound_id(node: Compound) -> Optional[str]:
		for kv in node.items:
			if kv.key == "id" and isinstance(kv.value, Scalar) and kv.value.kind == "string":
				return kv.value.value
		return None

	@staticmethod
	def _should_extract_text(text: str) -> bool:
		return isinstance(text, str) and text != ""

	@staticmethod
	def _escape_string(s: str) -> str:
		s = s.replace("\\", "\\\\")
		s = s.replace('"', '\\"')
		s = s.replace("\n", "\\n")
		s = s.replace("\t", "\\t")
		s = s.replace("\r", "\\r")
		return s

	def _load_snbt_document(self, path: Path) -> List[Any]:
		text = path.read_text(encoding="utf-8")
		parser = _FTBSnbtParser(text)
		return parser.parse_document()

	def _save_snbt_document(self, path: Path, roots: List[Any]) -> None:
		text = self._serializer.dumps_document(roots)
		path.write_text(text, encoding="utf-8", newline="\n")

	@staticmethod
	def _load_json(path: Path) -> Dict[str, Any]:
		with path.open("r", encoding="utf-8") as f:
			return json.load(f)

	@staticmethod
	def _save_json(path: Path, data: Dict[str, Any]) -> None:
		with path.open("w", encoding="utf-8", newline="\n") as f:
			json.dump(data, f, ensure_ascii=False, indent=2)

	@staticmethod
	def _reset_dir(path: Path) -> None:
		if path.exists():
			shutil.rmtree(path)
		path.mkdir(parents=True, exist_ok=True)
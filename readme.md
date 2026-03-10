# AI抽卡抽出来的ftbquests一键翻译工具
自己在1.20.1的包上实验过，效果还行
# 使用方法
## 安装依赖
* exe版本可跳过
```bash
pip install wxPython openai requests
```
## 填入API
选择OpenAI兼容的供应商

填写 url + APIKey + 模型ID

## 配置执行方式
选择并行请求数量和没请求翻译多少个key

（考虑供应商是否限制，和模型上下文限制）

## 中间文件

脚本会ftbquest父目录下生成ftb_trans文件夹

其中有：
* ftbquests_lang_key （提取出来用id占位符替换文本文件的snbt）
* ftbquests_translated （翻译后的结果，最终用这个替换原来的ftbquests）
* lang_index.json （id -》 文本位置的映射表）
* lang_original.json （待翻译文件 key value 对）
* lang_zh_cn.json （翻译后文件 key value 对）


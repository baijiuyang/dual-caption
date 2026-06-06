"""UI string translations (English / Simplified Chinese) for the Streamlit app.

`TRANSLATIONS[lang][key]` holds page text; `COMPONENT_LABELS[lang]` holds the
strings passed into the Step 2 editor component. Use `{placeholder}` fields and
`str.format(**kwargs)` to fill in dynamic values.
"""

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "page_title": "Dual Caption",
        "title": "Dual Caption Workflow",
        "subtitle": "Make English & Chinese subtitles. Audio → transcript JSON → manual corrections → SRT.",
        "lang_button": "中文",  # shown when UI is English (switches to Chinese)
        # Feedback
        "feedback_button": "💬 Feedback",
        "feedback_title": "Send feedback",
        "feedback_intro": "Found a bug or have an idea? I'd love to hear it.",
        "feedback_msg_label": "Your feedback",
        "feedback_msg_placeholder": "What worked, what didn't, what you'd like to see...",
        "feedback_email_label": "Your email (optional — only if you'd like a reply)",
        "feedback_send": "Send",
        "feedback_empty": "Please enter some feedback first.",
        "feedback_sent": "Thanks! Your feedback was sent.",
        "feedback_not_configured": "Feedback isn't set up on the server yet.",
        "feedback_error": "Could not send feedback: {err}",
        # Step 1
        "step1_header": "Step 1 — Transcribe audio to JSON",
        "step1_desc": "Upload an audio file. Soniox transcribes it and returns a word-level JSON with `start_ms`, `end_ms`, and `confidence` for every token.",
        "soniox_warn": "`SONIOX_API_KEY` is not set. Configure it via `.env` (local) or Streamlit secrets (cloud) to enable this step.",
        "audio_file_label": "Audio file",
        "transcribe_button": "Transcribe",
        "transcribing": "Uploading and transcribing...",
        "transcribe_failed": "Transcription failed: {err}",
        "transcript_ready": "Transcript ready. Correct it in Step 2, or download the raw JSON below.",
        "download_transcript": "Download transcript JSON",
        # Step 2
        "step2_header": "Step 2 — Correct the transcript while listening",
        "step2_desc": "Play the audio and follow along — the line being spoken is highlighted. Click ▶ on any line to jump there. Edit lines in place, then **Apply corrections**. Word-level timestamps are preserved: unchanged words keep their exact times, and split/inserted words get proportional ones.",
        "step2_no_transcript": "No transcript loaded — upload one to correct it",
        "transcript_json_label": "Transcript JSON",
        "matching_audio_label": "Matching audio",
        "decode_json_failed": "Could not decode JSON as UTF-8.",
        "parse_json_failed": "Could not parse transcript JSON: {err}",
        "corrections_applied": "Corrections applied ({n} line(s) edited). Download below or continue to Step 3.",
        "download_corrected": "Download corrected JSON",
        # Step 3
        "step3_header": "Step 3 — Convert corrected JSON to SRT",
        "step3_desc": "Applies rule-based segmentation (temporal proximity, punctuation, visual length caps), then an LLM refinement pass that merges fragments, splits over-long lines, and tightens punctuation. Output is an SRT ready for your video editor.",
        "openai_warn": "`OPENAI_API_KEY` is not set. Configure it via `.env` (local) or Streamlit secrets (cloud) to enable this step.",
        "using_corrected": "Using the corrected transcript from Step 2.",
        "upload_other_json": "Upload a different JSON instead",
        "corrected_json_label": "Corrected transcript JSON",
        "decode_failed": "Could not decode file as UTF-8.",
        "use_llm_label": "LLM refinement (merge fragments, split over-long lines)",
        "use_summary_label": "Generate video summary for grounding (improves error correction)",
        "convert_button": "Convert to SRT",
        "generating_srt": "Generating SRT...",
        "conversion_failed": "Conversion failed: {err}",
        "srt_ready": "SRT ready.",
        "download_srt": "Download SRT",
        "preview_srt": "Preview SRT",
        # Optional dual
        "dual_header": "Optional — Add Chinese–English dual subtitles",
        "dual_desc": "Translate each line to the other language and stack it below the original. Uses the SRT from Step 3 automatically, or upload your own.",
        "openai_warn_dual": "`OPENAI_API_KEY` is not set. Configure it to enable dual subtitles.",
        "using_srt": "Using the SRT from Step 3.",
        "upload_other_srt": "Upload a different SRT instead",
        "srt_file_label": "SRT file",
        "add_dual_button": "Add dual subtitles",
        "translating": "Translating...",
        "dual_failed": "Dual caption failed: {err}",
        "dual_ready": "Dual SRT ready.",
        "download_dual": "Download dual SRT",
        "preview_dual": "Preview dual SRT",
    },
    "zh": {
        "page_title": "双语字幕",
        "title": "双语字幕工作流",
        "subtitle": "制作中文和英文字幕。音频 → 转录 JSON → 手动校对 → SRT",
        "lang_button": "English",  # shown when UI is Chinese (switches to English)
        # Feedback
        "feedback_button": "💬 反馈",
        "feedback_title": "发送反馈",
        "feedback_intro": "发现问题或有好的想法？欢迎告诉我。",
        "feedback_msg_label": "您的反馈",
        "feedback_msg_placeholder": "哪里好用、哪里有问题、希望增加什么……",
        "feedback_email_label": "您的邮箱（可选 — 如需回复请填写）",
        "feedback_send": "发送",
        "feedback_empty": "请先填写反馈内容。",
        "feedback_sent": "谢谢！您的反馈已发送。",
        "feedback_not_configured": "服务器尚未配置反馈功能。",
        "feedback_error": "无法发送反馈：{err}",
        # Step 1
        "step1_header": "步骤 1 — 将音频转录为 JSON",
        "step1_desc": "上传音频文件。Soniox 会进行转录，并为每个词返回包含 `start_ms`、`end_ms` 和 `confidence` 的词级 JSON。",
        "soniox_warn": "未设置 `SONIOX_API_KEY`。请在 `.env`（本地）或 Streamlit secrets（云端）中配置以启用此步骤。",
        "audio_file_label": "音频文件",
        "transcribe_button": "开始转录",
        "transcribing": "正在上传并转录……",
        "transcribe_failed": "转录失败：{err}",
        "transcript_ready": "转录完成。可在步骤 2 中校对，或在下方下载原始 JSON。",
        "download_transcript": "下载转录 JSON",
        # Step 2
        "step2_header": "步骤 2 — 边听边校对转录",
        "step2_desc": "播放音频并跟读 — 正在朗读的那一句会高亮显示。点击任意一句的 ▶ 可跳转到该处。可直接编辑文字，然后点击 **应用更正**。词级时间戳会被保留：未改动的词保持原有时间，拆分／新增的词会按比例分配时间。",
        "step2_no_transcript": "尚未加载转录 — 上传一个以进行校对",
        "transcript_json_label": "转录 JSON",
        "matching_audio_label": "对应音频",
        "decode_json_failed": "无法以 UTF-8 解码该 JSON。",
        "parse_json_failed": "无法解析转录 JSON：{err}",
        "corrections_applied": "已应用更正（已编辑 {n} 句）。可在下方下载，或继续进行步骤 3。",
        "download_corrected": "下载校对后的 JSON",
        # Step 3
        "step3_header": "步骤 3 — 将校对后的 JSON 转换为 SRT",
        "step3_desc": "先进行基于规则的分句（时间邻近度、标点、显示长度上限），再通过大模型优化：合并碎片、拆分过长行、规整标点。输出可直接用于视频剪辑的 SRT。",
        "openai_warn": "未设置 `OPENAI_API_KEY`。请在 `.env`（本地）或 Streamlit secrets（云端）中配置以启用此步骤。",
        "using_corrected": "正在使用步骤 2 的校对结果。",
        "upload_other_json": "改为上传其他 JSON",
        "corrected_json_label": "校对后的转录 JSON",
        "decode_failed": "无法以 UTF-8 解码该文件。",
        "use_llm_label": "大模型优化（合并碎片、拆分过长行）",
        "use_summary_label": "生成视频摘要作为背景（提升纠错效果）",
        "convert_button": "转换为 SRT",
        "generating_srt": "正在生成 SRT……",
        "conversion_failed": "转换失败：{err}",
        "srt_ready": "SRT 已就绪。",
        "download_srt": "下载 SRT",
        "preview_srt": "预览 SRT",
        # Optional dual
        "dual_header": "可选 — 添加中英双语字幕",
        "dual_desc": "将每一行翻译为另一种语言，并叠加在原文下方。会自动使用步骤 3 的 SRT，也可自行上传。",
        "openai_warn_dual": "未设置 `OPENAI_API_KEY`。请配置后启用双语字幕。",
        "using_srt": "正在使用步骤 3 的 SRT。",
        "upload_other_srt": "改为上传其他 SRT",
        "srt_file_label": "SRT 文件",
        "add_dual_button": "添加双语字幕",
        "translating": "正在翻译……",
        "dual_failed": "双语字幕生成失败：{err}",
        "dual_ready": "双语 SRT 已就绪。",
        "download_dual": "下载双语 SRT",
        "preview_dual": "预览双语 SRT",
    },
}

# Strings rendered inside the Step 2 editor component (passed in as args).
COMPONENT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "apply": "Apply corrections",
        "play_from": "Play from here",
        "counter_active": "Line {i} / {n}",
        "counter_idle": "{n} lines",
        "applied_edited": "Applied — {n} line(s) edited. See download / Step 3 below.",
        "applied_none": "Applied — no changes detected.",
    },
    "zh": {
        "apply": "应用更正",
        "play_from": "从此处播放",
        "counter_active": "第 {i} / {n} 句",
        "counter_idle": "共 {n} 句",
        "applied_edited": "已应用 — 已编辑 {n} 句。请见下方下载 / 步骤 3。",
        "applied_none": "已应用 — 未检测到更改。",
    },
}


def detect_lang(accept_language: str | None) -> str:
    """Pick a default UI language from a browser Accept-Language header."""
    if accept_language and accept_language.strip().lower().startswith("zh"):
        return "zh"
    return "en"

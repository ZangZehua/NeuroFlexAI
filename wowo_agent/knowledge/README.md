# 本地知识库

将文件放在此目录，或通过 Web 界面上传。支持：

- `.pdf`、`.docx`
- `.txt`、`.md`、`.py`、`.json`、`.yaml`、`.yml`、`.csv`、`.log`

上传后会调用 OpenAI Embedding（默认 `text-embedding-3-small`）建立向量索引，
索引保存在 `.rag_index.json`。Agent / Web 问答会基于向量相似度检索相关片段。

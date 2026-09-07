# work-mac 的 Homebrew 软件清单（不是版本锁文件）。
#
# 只登记 2026-09-07 用 `brew list --versions` 实测确认归 Homebrew 所有的 formula。
# 刻意不在这里的项及原因：
#   ripgrep  —— `rg` 由 Trae CLI 安装器投放在 ~/.local/bin，写进来等于新造一个多渠道冲突
#   jq       —— 生效的是系统 /usr/bin/jq（jq-1.7.1-apple），brew 并未安装它
#   pnpm     —— /opt/homebrew/bin/pnpm 是 brew node 里的 corepack shim，不是独立 formula
#   codex    —— npm 全局包 @openai/codex，不是 brew formula
#   cask     —— 桌面应用走自己的更新渠道，v1 不管
#
# 只管理选中的软件，不把本机全部 Homebrew 安装导出成默认清单。

brew "node"      # 24.3.0
brew "uv"        # 0.8.4
brew "gh"        # 2.96.0，GitHub CLI
brew "pipx"      # 1.11.1，aiwb 等 Python CLI 的安装渠道
brew "python@3.11"  # 3.11.15，开发用 Python；系统 3.9.6 保持不动
brew "fzf"       # 0.64.0
brew "wget"      # 1.25.0

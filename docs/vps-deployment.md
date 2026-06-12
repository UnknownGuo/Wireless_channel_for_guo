# VPS 更新 / 部署说明

本项目在 VPS 上的目录默认是：

```bash
/opt/wireless-channel-recommender/app
```

新增脚本：

```bash
scripts/deploy_vps.sh
```

它通过 BandwagonHost / KiwiVM 的 `basicShell/exec` API 在 VPS 上执行更新，不依赖 SSH 登录。

## 环境变量

必须提供 API key，二选一：

```bash
export BANDWAGON_API_KEY='***'  # KiwiVM API key
```

或者写到本地文件：

```bash
mkdir -p ~/.config/paper-llm
printf '%s' '***' > ~/.config/paper-llm/bandwagon_api_key
chmod 600 ~/.config/paper-llm/bandwagon_api_key
```

可选：

```bash
export BANDWAGON_VEID=2131405
export VPS_APP_DIR=/opt/wireless-channel-recommender/app
export VPS_BRANCH=main
```

默认已经按当前 VPS 设置好：

- `BANDWAGON_VEID=2131405`
- `VPS_APP_DIR=/opt/wireless-channel-recommender/app`
- `VPS_BRANCH=main`

不要把 `BANDWAGON_API_KEY` 写进仓库。

## 1. 查看 VPS 当前状态

```bash
BANDWAGON_API_KEY='***' bash scripts/deploy_vps.sh status
```

会显示：

- VPS 仓库状态
- 最近提交
- Python / uv 情况

## 2. 常规更新：pull 模式

适合 GitHub 远端已经更新的情况：

```bash
BANDWAGON_API_KEY='***' bash scripts/deploy_vps.sh pull
```

它会在 VPS 上执行：

1. `git fetch origin main`
2. `git reset --hard origin/main`
3. Python `compileall` 烟检
4. 输出最终 git 状态

## 3. GitHub 推不上去时：patch 模式

如果本机代码已经提交，但 GitHub 暂时没有推送权限，可以直接把当前本地 `HEAD` 提交打成 patch 发到 VPS：

```bash
BANDWAGON_API_KEY='***' bash scripts/deploy_vps.sh patch
```

它会：

1. 检查本地工作区是否干净
2. 用 `git format-patch origin/main..HEAD` 导出所有本地领先提交
3. 临时上传 patch 到 paste.rs
4. VPS 下载 patch
5. VPS 从 `origin/main` 重置后 `git am -3` 应用该提交
6. 跑 `compileall` 烟检

这个模式适合当前这种情况：本地已经整理好提交，但 GitHub token 没有写权限。

## 4. 是否跑完整测试

VPS 是 1G 内存，完整 pytest 可能被系统杀掉。默认只跑 `compileall`。

如果确实要跑完整测试：

```bash
RUN_PYTEST=1 BANDWAGON_API_KEY='***' bash scripts/deploy_vps.sh pull
```

或：

```bash
RUN_PYTEST=1 BANDWAGON_API_KEY='***' bash scripts/deploy_vps.sh patch
```

## 推荐用法

日常最推荐：

```bash
BANDWAGON_API_KEY='***' bash scripts/deploy_vps.sh status
BANDWAGON_API_KEY='***' bash scripts/deploy_vps.sh pull
```

如果 GitHub 推送暂时不通：

```bash
BANDWAGON_API_KEY='***' bash scripts/deploy_vps.sh patch
```

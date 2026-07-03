#!/usr/bin/env bash
#
# 手动上传 .deb 到 GitHub Releases
#
# 使用方式：
#   ./scripts/upload-release.sh
#
# 该脚本必须由用户主动运行，不会自动触发。
# 运行前请先配置 GitHub Token（见下文"Token 设置方式"）。
#
# Token 设置方式（按优先级）：
#   1. 环境变量：export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
#   2. 本地文件：echo "ghp_xxxxxxxxxxxx" > ~/.config/ubuntu-speak/github_token
#      并将权限设置为 600：chmod 600 ~/.config/ubuntu-speak/github_token
#
# 注意：Token 文件路径已通过 .gitignore 排除，不会进入 Git 仓库。

set -euo pipefail

REPO="briup1/ubuntu_speak"
TOKEN_FILE="${HOME}/.config/ubuntu-speak/github_token"

# 查找 releases/ 目录：优先使用项目源码父目录（AGENTS.md 约定位置）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PARENT_DIR="$(cd "${PROJECT_DIR}/.." && pwd)"

if [[ -d "${PROJECT_DIR}/releases" ]]; then
    RELEASES_DIR="${PROJECT_DIR}/releases"
elif [[ -d "${PARENT_DIR}/releases" ]]; then
    RELEASES_DIR="${PARENT_DIR}/releases"
else
    RELEASES_DIR="${PROJECT_DIR}/releases"
fi

# --------------- 工具检查 ---------------

command -v curl >/dev/null 2>&1 || { echo "错误：未安装 curl"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "错误：未安装 python3"; exit 1; }

# --------------- Token 获取 ---------------

get_token() {
    local token=""

    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        token="${GITHUB_TOKEN}"
        echo "[信息] 已从环境变量 GITHUB_TOKEN 读取 Token" >&2
    elif [[ -f "${TOKEN_FILE}" ]]; then
        token="$(cat "${TOKEN_FILE}" | tr -d '[:space:]')"
        echo "[信息] 已从本地文件 ${TOKEN_FILE} 读取 Token" >&2
    fi

    if [[ -z "${token}" ]]; then
        echo "错误：未找到 GitHub Token。" >&2
        echo "请按以下方式之一设置 Token：" >&2
        echo "  1. export GITHUB_TOKEN='ghp_xxxxxxxxxxxx'" >&2
        echo "  2. echo 'ghp_xxxxxxxxxxxx' \u003e ${TOKEN_FILE}" >&2
        echo "     chmod 600 ${TOKEN_FILE}" >&2
        echo "获取 Token 地址：https://github.com/settings/tokens/new" >&2
        exit 1
    fi

    echo "${token}"
}

TOKEN="$(get_token)"

# --------------- 查找 .deb 文件 ---------------

if [[ ! -d "${RELEASES_DIR}" ]]; then
    echo "错误：打包产物目录不存在：${RELEASES_DIR}"
    echo "请先执行 dpkg-buildpackage 并把 .deb 移动到 releases/ 目录。"
    exit 1
fi

mapfile -t DEB_FILES < <(find "${RELEASES_DIR}" -maxdepth 1 -name '*.deb' -type f | sort)

if [[ ${#DEB_FILES[@]} -eq 0 ]]; then
    echo "错误：在 ${RELEASES_DIR} 下未找到 .deb 文件"
    exit 1
fi

# 如果只有一个 .deb，直接使用；否则让用户选择
if [[ ${#DEB_FILES[@]} -eq 1 ]]; then
    SELECTED_DEB="${DEB_FILES[0]}"
    echo "[信息] 仅找到一个 .deb：$(basename "${SELECTED_DEB}")"
else
    echo "请选择要上传的 .deb 文件："
    for i in "${!DEB_FILES[@]}"; do
        echo "  $((i + 1))) $(basename "${DEB_FILES[i]}")"
    done
    read -rp "输入编号 [1-${#DEB_FILES[@]}]: " choice
    if ! [[ "${choice}" =~ ^[0-9]+$ ]] || [[ "${choice}" -lt 1 ]] || [[ "${choice}" -gt ${#DEB_FILES[@]} ]]; then
        echo "错误：无效选择"
        exit 1
    fi
    SELECTED_DEB="${DEB_FILES[$((choice - 1))]}"
fi

DEB_BASENAME="$(basename "${SELECTED_DEB}")"

# 从文件名提取版本号，例如 ubuntu-speak_0.3.6-1_all.deb → 0.3.6
VERSION="$(echo "${DEB_BASENAME}" | sed -E 's/^[^_]+_([0-9]+\.[0-9]+\.[0-9]+)-[0-9]+_.*\.deb$/\1/')"
if [[ -z "${VERSION}" ]] || [[ "${VERSION}" == "${DEB_BASENAME}" ]]; then
    echo "错误：无法从文件名解析版本号：${DEB_BASENAME}"
    echo "文件名格式应为：ubuntu-speak_X.Y.Z-N_all.deb"
    exit 1
fi

TAG="v${VERSION}"
RELEASE_NAME="v${VERSION}"

# --------------- 用户确认 ---------------

echo ""
echo "即将执行以下操作："
echo "  仓库：${REPO}"
echo "  标签：${TAG}"
echo "  版本：${RELEASE_NAME}"
echo "  文件：${SELECTED_DEB}"
echo ""
read -rp "确认上传？输入 yes 继续: " confirm
if [[ "${confirm}" != "yes" ]]; then
    echo "已取消上传"
    exit 0
fi

# --------------- 检查 Release 是否已存在 ---------------

echo "[信息] 检查 Release ${TAG} 是否已存在..."
EXISTING_RELEASE=$(curl -s \
    -H "Authorization: token ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${REPO}/releases/tags/${TAG}" || true)

if echo "${EXISTING_RELEASE}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" >/dev/null 2>&1 && \
   [[ -n "$(echo "${EXISTING_RELEASE}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)" ]]; then
    echo "错误：Release ${TAG} 已存在"
    echo "请先删除旧 Release，或选择另一个版本上传"
    exit 1
fi

# --------------- 创建 Release ---------------

# 构造 body 后通过 jq/python3 生成 JSON，避免 shell 转义问题
BODY=$(cat <<EOF
Ubuntu 语音输入法 ubuntu-speak ${RELEASE_NAME}

- 支持 toggle 模式录音
- 支持 evdev 按住说话
- 包含系统托盘指示器与桌面通知

## 安装

\`\`\`bash
sudo dpkg -i ${DEB_BASENAME}
sudo apt-get install -f
\`\`\`
EOF
)

CREATE_PAYLOAD=$(python3 -c "
import json, sys
print(json.dumps({
    'tag_name': '${TAG}',
    'target_commitish': 'main',
    'name': '${RELEASE_NAME}',
    'body': '''${BODY}''',
    'draft': False,
    'prerelease': False
}))
")

echo "[信息] 创建 Release ${TAG}..."
CREATE_RESPONSE=$(curl -s -X POST \
    -H "Authorization: token ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "Content-Type: application/json" \
    "https://api.github.com/repos/${REPO}/releases" \
    -d "${CREATE_PAYLOAD}")

UPLOAD_URL=$(echo "${CREATE_RESPONSE}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('upload_url','').replace('{?name,label}',''))" 2>/dev/null || true)
RELEASE_ID=$(echo "${CREATE_RESPONSE}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)

if [[ -z "${UPLOAD_URL}" ]] || [[ -z "${RELEASE_ID}" ]]; then
    echo "错误：创建 Release 失败"
    echo "GitHub 响应："
    echo "${CREATE_RESPONSE}" | python3 -m json.tool 2>/dev/null || echo "${CREATE_RESPONSE}"
    exit 1
fi

echo "[信息] Release 创建成功，ID: ${RELEASE_ID}"

# --------------- 上传 .deb ---------------

echo "[信息] 上传 ${DEB_BASENAME}..."
UPLOAD_RESPONSE=$(curl -s -X POST \
    -H "Authorization: token ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "Content-Type: application/octet-stream" \
    --data-binary "@${SELECTED_DEB}" \
    "${UPLOAD_URL}?name=${DEB_BASENAME}")

ASSET_ID=$(echo "${UPLOAD_RESPONSE}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)
if [[ -n "${ASSET_ID}" ]]; then
    echo "[成功] 上传完成！"
    echo "Release 页面：https://github.com/${REPO}/releases/tag/${TAG}"
else
    echo "错误：上传 .deb 失败"
    echo "GitHub 响应："
    echo "${UPLOAD_RESPONSE}" | python3 -m json.tool 2>/dev/null || echo "${UPLOAD_RESPONSE}"
    exit 1
fi

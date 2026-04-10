import os
import alibabacloud_oss_v2 as oss

def local_to_link(path: str) -> str:
    """
    将本地音频文件上传至阿里云 OSS 并返回文件的公共访问 URL。

    参数:
        path (str): 本地需要上传的文件路径。

    返回:
        str: 上传成功后的文件可访问 URL。
    """
    bucket = "wcc-ai-app"
    key = f"link/{os.path.basename(path)}"
    region = "cn-beijing"

    # 1. 加载凭证信息
    credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()

    # 2. 初始化配置
    cfg = oss.config.load_default()
    cfg.credentials_provider = credentials_provider
    cfg.region = region

    # 3. 创建 OSS 客户端
    client = oss.Client(cfg)

    # 4. 执行上传
    result = client.put_object_from_file(
        oss.PutObjectRequest(
            bucket=bucket,
            key=key
        ),
        path
    )

    # 5. 校验并拼接返回 URL
    if result.status_code == 200:
        # 如果没有显式提供 endpoint，则使用阿里云默认的公网 Endpoint 格式
        actual_endpoint = f"oss-{region}.aliyuncs.com"

        # 剥离前缀以确保 URL 拼接正确
        actual_endpoint = actual_endpoint.replace("http://", "").replace("https://", "")

        # 拼接并返回完整 URL (默认使用 https)
        file_url = f"https://{bucket}.{actual_endpoint}/{key}"
        return file_url
    else:
        raise Exception(f"文件上传失败! 状态码: {result.status_code}, Request ID: {result.request_id}")
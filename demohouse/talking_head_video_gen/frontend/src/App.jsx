import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  FormControlLabel,
  IconButton,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import AddIcon from "@mui/icons-material/Add";
import LinkIcon from "@mui/icons-material/Link";
import EditIcon from "@mui/icons-material/Edit";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import ReplayIcon from "@mui/icons-material/Replay";
import MovieCreationIcon from "@mui/icons-material/MovieCreation";
import SendIcon from "@mui/icons-material/Send";
import {
  absUrl,
  createSession,
  step1Extract,
  step2RewriteOnly,
  step2TranscribeRewrite,
  step3Generate,
  step4Tts,
  step5Align,
  step6Publish,
  uploadAsset,
} from "./api";

const PLATFORMS = [
  { value: "douyin", label: "抖音" },
  { value: "kuaishou", label: "快手" },
  { value: "wechat_channels", label: "视频号" },
  { value: "bilibili", label: "Bilibili" },
  { value: "xiaohongshu", label: "小红书" },
];

const tooltipProps = {
  arrow: true,
  slotProps: {
    tooltip: {
      sx: {
        bgcolor: "#111827",
        color: "#fff",
        fontSize: 12,
        px: 1.25,
        py: 0.75,
        borderRadius: 1.5,
        boxShadow: 4,
      },
    },
    arrow: {
      sx: { color: "#111827" },
    },
  },
};

const roundIconButtonSx = {
  width: 40,
  height: 40,
  borderRadius: "50%",
  border: "1px solid",
  borderColor: "divider",
  bgcolor: "background.paper",
  boxShadow: 2,
  transition: "box-shadow 0.2s ease, transform 0.2s ease",
  "&:hover": {
    boxShadow: 4,
    transform: "translateY(-1px)",
  },
  "&.Mui-disabled": {
    boxShadow: "none",
    transform: "none",
    borderColor: "transparent",
  },
};

const dashedPreviewRadius = 1;

export default function App() {
  const [sessionId, setSessionId] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState({ type: "info", text: "准备开始" });
  const [notice, setNotice] = useState("");
  const [actionLoading, setActionLoading] = useState({
    extract: false,
    rewrite: false,
    generate: false,
    finalCompose: false,
  });

  const [sharelink, setSharelink] = useState("");
  const [transcript, setTranscript] = useState("");

  const [firstFrameFile, setFirstFrameFile] = useState(null);
  const [speakerFile, setSpeakerFile] = useState(null);
  const [firstFramePreviewUrl, setFirstFramePreviewUrl] = useState("");
  const [speakerPreviewUrl, setSpeakerPreviewUrl] = useState("");
  const [prompt, setPrompt] = useState("一位年轻男销售面对镜头微笑地说话，配合着自然的手势动作，背景是简洁的办公室环境。");

  const [artifacts, setArtifacts] = useState({
    firstFrameUrl: "",
    speakerAudioUrl: "",
    generatedVideoUrl: "",
    ttsAudioUrl: "",
    finalVideoUrl: "",
  });

  const [publish, setPublish] = useState({
    title: "",
    description: "",
    platforms: [],
  });
  const [artifactVersion, setArtifactVersion] = useState(String(Date.now()));

  const readyForMiddle = Boolean(transcript.trim());
  const readyForRight = Boolean(artifacts.generatedVideoUrl && artifacts.ttsAudioUrl);
  const hasGeneratedVideo = Boolean(artifacts.generatedVideoUrl);
  const firstFrameDisplayUrl = firstFramePreviewUrl || artifacts.firstFrameUrl;
  const speakerDisplayUrl = speakerPreviewUrl || artifacts.speakerAudioUrl;

  const sessionLabel = useMemo(() => (sessionId ? `Session: ${sessionId}` : "Session: 未初始化"), [sessionId]);

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      try {
        const data = await createSession();
        setSessionId(data.session_id);
        setMessage({ type: "success", text: "会话创建成功" });
      } catch (err) {
        setMessage({ type: "error", text: `会话创建失败: ${err.message}` });
      } finally {
        setLoading(false);
      }
    };
    init();
  }, []);

  useEffect(() => {
    if (!firstFrameFile) {
      setFirstFramePreviewUrl("");
      return;
    }
    const url = URL.createObjectURL(firstFrameFile);
    setFirstFramePreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [firstFrameFile]);

  useEffect(() => {
    if (!speakerFile) {
      setSpeakerPreviewUrl("");
      return;
    }
    const url = URL.createObjectURL(speakerFile);
    setSpeakerPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [speakerFile]);

  const syncSessionState = (state, version = artifactVersion) => {
    setTranscript(state.rewritten_text || state.original_text || transcript);
    setNotice(state.notice || "");
    setArtifacts((prev) => ({
      ...prev,
      firstFrameUrl: absUrl(state.first_frame_url, version),
      speakerAudioUrl: absUrl(state.speaker_audio_url, version),
      generatedVideoUrl: absUrl(state.generated_video_url, version),
      ttsAudioUrl: absUrl(state.tts_audio_url, version),
      finalVideoUrl: absUrl(state.final_video_url, version),
    }));
  };

  const runLeftStep = async () => {
    if (!sessionId) {
      return;
    }
    if (!sharelink.trim()) {
      setMessage({ type: "warning", text: "请先输入抖音分享链接" });
      return;
    }

    setLoading(true);
    setActionLoading((prev) => ({ ...prev, extract: true }));
    setMessage({ type: "info", text: "正在提取音频并转写改写文案..." });
    try {
      await step1Extract({ session_id: sessionId, sharelink });
      const state = await step2TranscribeRewrite({ session_id: sessionId });
      syncSessionState(state);
      setMessage({ type: "success", text: "文案提取成功，可编辑后进入下一步" });
    } catch (err) {
      setMessage({ type: "error", text: err.response?.data?.detail || err.message });
    } finally {
      setLoading(false);
      setActionLoading((prev) => ({ ...prev, extract: false }));
    }
  };

  const rewriteEditedTranscript = async () => {
    if (!sessionId || !transcript.trim()) {
      setMessage({ type: "warning", text: "请先输入文案" });
      return;
    }
    setLoading(true);
    setActionLoading((prev) => ({ ...prev, rewrite: true }));
    setMessage({ type: "info", text: "正在改写文案..." });
    try {
      const state = await step2RewriteOnly({ session_id: sessionId, transcript });
      syncSessionState(state);
      setMessage({ type: "success", text: "文案改写完成" });
    } catch (err) {
      setMessage({ type: "error", text: err.response?.data?.detail || err.message });
    } finally {
      setLoading(false);
      setActionLoading((prev) => ({ ...prev, rewrite: false }));
    }
  };

  const uploadPendingAssets = async () => {
    if (!sessionId) {
      return;
    }
    if (!firstFrameFile && !speakerFile) {
      return;
    }

    if (firstFrameFile) {
      const res = await uploadAsset(sessionId, "first_frame", firstFrameFile);
      setArtifacts((prev) => ({ ...prev, firstFrameUrl: absUrl(res.url) }));
    }
    if (speakerFile) {
      const res = await uploadAsset(sessionId, "speaker_audio", speakerFile);
      setArtifacts((prev) => ({ ...prev, speakerAudioUrl: absUrl(res.url) }));
    }
    setFirstFrameFile(null);
    setSpeakerFile(null);
  };

  const generateMiddle = async (force = false) => {
    if (!sessionId) {
      return;
    }
    if (!readyForMiddle) {
      setMessage({ type: "warning", text: "请先完成左侧文案与素材" });
      return;
    }

    setLoading(true);
    setActionLoading((prev) => ({ ...prev, generate: true }));
    setNotice("");
    setMessage({ type: "info", text: "正在准备生成流程..." });
    try {
      if (firstFrameFile || speakerFile) {
        setMessage({ type: "info", text: "正在自动上传素材..." });
        await uploadPendingAssets();
      }

      setMessage({ type: "info", text: "正在生成视频和TTS..." });
      const state3 = await step3Generate({
        session_id: sessionId,
        prompt: prompt || transcript,
        duration: 11,
        force,
      });
      const state4 = await step4Tts({
        session_id: sessionId,
        text: transcript,
        force,
      });
      const nextVersion = String(Date.now());
      setArtifactVersion(nextVersion);
      syncSessionState(state3, nextVersion);
      syncSessionState(state4, nextVersion);
      if (state3.notice || state4.notice) {
        setMessage({ type: "warning", text: "中间流程未完全执行，请先处理提示信息" });
      } else {
        setMessage({ type: "success", text: "中间流程生成完成，可进入下一步" });
      }
    } catch (err) {
      setMessage({ type: "error", text: err.response?.data?.detail || err.message });
    } finally {
      setLoading(false);
      setActionLoading((prev) => ({ ...prev, generate: false }));
    }
  };

  const runFinalCompose = async () => {
    if (!sessionId) {
      return;
    }
    setLoading(true);
    setActionLoading((prev) => ({ ...prev, finalCompose: true }));
    setMessage({ type: "info", text: "正在进行最终唇形合成..." });
    try {
      const state = await step5Align({ session_id: sessionId });
      const nextVersion = String(Date.now());
      setArtifactVersion(nextVersion);
      syncSessionState(state, nextVersion);
      setMessage({ type: "success", text: "最终视频已生成" });
    } catch (err) {
      setMessage({ type: "error", text: err.response?.data?.detail || err.message });
    } finally {
      setLoading(false);
      setActionLoading((prev) => ({ ...prev, finalCompose: false }));
    }
  };

  const doPublish = async () => {
    if (!sessionId || publish.platforms.length === 0) {
      setMessage({ type: "warning", text: "请选择发布平台" });
      return;
    }
    setLoading(true);
    try {
      await step6Publish({
        session_id: sessionId,
        platforms: publish.platforms,
        title: publish.title,
        description: publish.description,
      });
      setMessage({ type: "success", text: "已提交发布请求（当前后端发布接口为占位实现）" });
    } catch (err) {
      setMessage({ type: "error", text: err.response?.data?.detail || err.message });
    } finally {
      setLoading(false);
    }
  };

  const togglePlatform = (value) => {
    setPublish((prev) => {
      const has = prev.platforms.includes(value);
      return {
        ...prev,
        platforms: has ? prev.platforms.filter((x) => x !== value) : [...prev.platforms, value],
      };
    });
  };

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" justifyContent="flex-start" alignItems="center" mb={2}>
        <Stack direction="row" spacing={1} alignItems="center">
          <AutoAwesomeIcon color="primary" />
          <Typography variant="h5" fontWeight={600}>
            Talking Head Studio
          </Typography>
          <Chip size="small" label={sessionLabel} />
        </Stack>
      </Stack>

      <Alert severity={message.type} sx={{ mb: 2 }}>
        {message.text}
      </Alert>
      {notice ? (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {notice}
        </Alert>
      ) : null}

      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" },
          alignItems: "stretch",
        }}
      >
        <Card sx={{ minHeight: 720 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={600} gutterBottom>
              素材与文案
            </Typography>
            <TextField
              fullWidth
              label="抖音分享链接"
              value={sharelink}
              onChange={(e) => setSharelink(e.target.value)}
              multiline
              minRows={3}
              margin="normal"
            />
            <Tooltip title="提取文案" {...tooltipProps}>
              <span>
                <Box sx={{ position: "relative", display: "inline-flex" }}>
                  <IconButton color="primary" onClick={runLeftStep} disabled={loading} sx={roundIconButtonSx}>
                    <LinkIcon />
                  </IconButton>
                  {actionLoading.extract ? (
                    <CircularProgress size={54} thickness={3.5} sx={{ position: "absolute", top: -7, left: -7 }} />
                  ) : null}
                </Box>
              </span>
            </Tooltip>

            <Divider sx={{ my: 2 }} />

            <TextField
              fullWidth
              label="可编辑文案"
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              multiline
              minRows={12}
            />
            <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
              <Tooltip title="重新改写" {...tooltipProps}>
                <span>
                  <Box sx={{ position: "relative", display: "inline-flex" }}>
                    <IconButton color="primary" onClick={rewriteEditedTranscript} disabled={loading || !transcript.trim()} sx={roundIconButtonSx}>
                      <EditIcon />
                    </IconButton>
                    {actionLoading.rewrite ? (
                      <CircularProgress size={54} thickness={3.5} sx={{ position: "absolute", top: -7, left: -7 }} />
                    ) : null}
                  </Box>
                </span>
              </Tooltip>
            </Stack>

            <Divider sx={{ my: 2 }} />

            <Typography variant="subtitle2" gutterBottom>
              个人形象上传
            </Typography>
            <Stack spacing={1.5}>
              <Box
                component="label"
                sx={{
                  display: "block",
                  width: "100%",
                  minHeight: 140,
                  maxHeight: 180,
                  borderRadius: dashedPreviewRadius,
                  border: "1px dashed",
                  borderColor: "divider",
                  overflow: "hidden",
                  cursor: "pointer",
                  bgcolor: "background.paper",
                }}
              >
                <input
                  hidden
                  type="file"
                  accept="image/*"
                  onChange={(e) => setFirstFrameFile(e.target.files?.[0] || null)}
                />
                {firstFrameDisplayUrl ? (
                  <Box
                    component="img"
                    src={firstFrameDisplayUrl}
                    alt="first-frame-preview"
                    sx={{ width: "100%", height: "100%", maxHeight: 180, objectFit: "contain" }}
                  />
                ) : (
                  <Stack alignItems="center" justifyContent="center" sx={{ minHeight: 140, color: "text.secondary" }}>
                    <AddIcon />
                    <Typography variant="body2">上传正面图片</Typography>
                  </Stack>
                )}
              </Box>
              <Typography variant="subtitle2" gutterBottom>
                个人音色上传
              </Typography>
              <Stack direction="row" spacing={1} alignItems="stretch">
                <Box
                  sx={{
                    flex: 1,
                    height: roundIconButtonSx.height,
                    borderRadius: dashedPreviewRadius,
                    border: "1px dashed",
                    borderColor: "divider",
                    px: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    overflow: "hidden",
                  }}
                >
                  {speakerDisplayUrl ? (
                    <audio
                      controls
                      src={speakerDisplayUrl}
                      style={{ width: "100%", height: "100%", display: "block", borderRadius: 8 }}
                    />
                  ) : (
                    <Stack alignItems="center" justifyContent="center" sx={{ color: "text.secondary" }}>
                      <Typography variant="body2">录音预览</Typography>
                    </Stack>
                  )}
                </Box>
                <Tooltip title="上传录音" {...tooltipProps}>
                  <IconButton component="label" color="primary" sx={roundIconButtonSx}>
                    <AddIcon />
                    <input hidden type="file" accept="audio/*" onChange={(e) => setSpeakerFile(e.target.files?.[0] || null)} />
                  </IconButton>
                </Tooltip>
              </Stack>
            </Stack>
          </CardContent>
        </Card>

        <Card sx={{ minHeight: 720 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={600} gutterBottom>
              视频语音合成
            </Typography>

            <TextField
              fullWidth
              label="视频生成提示词"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              multiline
              minRows={3}
              margin="normal"
            />

            <Stack direction="row" spacing={1} mb={2}>
              <Tooltip title={hasGeneratedVideo ? "重新生成" : "生成"} {...tooltipProps}>
                <span>
                  <Box sx={{ position: "relative", display: "inline-flex" }}>
                    <IconButton
                      color="primary"
                      onClick={() => generateMiddle(hasGeneratedVideo)}
                      disabled={loading}
                      sx={roundIconButtonSx}
                    >
                      {hasGeneratedVideo ? <ReplayIcon /> : <PlayArrowIcon />}
                    </IconButton>
                    {actionLoading.generate ? (
                      <CircularProgress size={54} thickness={3.5} sx={{ position: "absolute", top: -7, left: -7 }} />
                    ) : null}
                  </Box>
                </span>
              </Tooltip>
            </Stack>

            <Typography variant="subtitle2" gutterBottom>
              TTS 结果
            </Typography>
            {artifacts.ttsAudioUrl ? (
              <audio controls src={artifacts.ttsAudioUrl} style={{ width: "100%" }} />
            ) : (
              <Typography color="text.secondary">暂无</Typography>
            )}

            <Typography variant="subtitle2" sx={{ mt: 2 }} gutterBottom>
              视频结果
            </Typography>
            {artifacts.generatedVideoUrl ? (
              <video controls src={artifacts.generatedVideoUrl} style={{ width: "100%", borderRadius: 8 }} />
            ) : (
              <Typography color="text.secondary">暂无</Typography>
            )}
          </CardContent>
        </Card>

        <Card sx={{ minHeight: 720 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={600} gutterBottom>
              最终合成与发布
            </Typography>

            <Tooltip title="生成最终视频" {...tooltipProps}>
              <span>
                <Box sx={{ position: "relative", display: "inline-flex" }}>
                  <IconButton color="primary" onClick={runFinalCompose} disabled={loading || !readyForRight} sx={roundIconButtonSx}>
                    <MovieCreationIcon />
                  </IconButton>
                  {actionLoading.finalCompose ? (
                    <CircularProgress size={54} thickness={3.5} sx={{ position: "absolute", top: -7, left: -7 }} />
                  ) : null}
                </Box>
              </span>
            </Tooltip>

            <Box sx={{ mt: 2 }}>
              {artifacts.finalVideoUrl ? (
                <video controls src={artifacts.finalVideoUrl} style={{ width: "100%", borderRadius: 8 }} />
              ) : (
                <Typography color="text.secondary">尚未生成最终视频</Typography>
              )}
            </Box>

            <Divider sx={{ my: 2 }} />

            <Typography variant="subtitle2">发布平台</Typography>
            <Stack>
              {PLATFORMS.map((item) => (
                <FormControlLabel
                  key={item.value}
                  control={
                    <Checkbox
                      checked={publish.platforms.includes(item.value)}
                      onChange={() => togglePlatform(item.value)}
                    />
                  }
                  label={item.label}
                />
              ))}
            </Stack>

            <TextField
              fullWidth
              label="发布标题"
              value={publish.title}
              onChange={(e) => setPublish((prev) => ({ ...prev, title: e.target.value }))}
              margin="dense"
            />
            <TextField
              fullWidth
              label="发布描述"
              value={publish.description}
              onChange={(e) => setPublish((prev) => ({ ...prev, description: e.target.value }))}
              margin="dense"
              multiline
              minRows={3}
            />
            <Tooltip title="勾选平台并发布" {...tooltipProps}>
              <span>
                <IconButton color="primary" onClick={doPublish} disabled={loading || !artifacts.finalVideoUrl} sx={{ ...roundIconButtonSx, mt: 1 }}>
                  <SendIcon />
                </IconButton>
              </span>
            </Tooltip>
          </CardContent>
        </Card>
      </Box>
    </Box>
  );
}


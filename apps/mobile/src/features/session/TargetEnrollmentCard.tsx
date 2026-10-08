import {
  confirmSessionTarget,
  fetchTransientSessionState,
  startSession,
  startSessionVisionAnalysis,
  submitVisionEnrollmentFrame,
  type PreparedSession,
  type VisionCandidate,
} from '@kinetiq/session-client';
import {CameraView, useCameraPermissions} from 'expo-camera';
import {useEffect, useRef, useState} from 'react';
import {Image, Pressable, StyleSheet, Text, View} from 'react-native';
import {visionTrackingMessage} from './visionTrackingMessage';

interface Props {
  authorization: string;
  endpoint: string;
  session: PreparedSession;
  onSessionChange: (session: PreparedSession) => void;
}

interface CapturedEnrollmentFrame {
  base64: string;
  uri: string;
  width: number;
  height: number;
}

export function TargetEnrollmentCard({authorization, endpoint, session, onSessionChange}: Props) {
  const camera = useRef<CameraView>(null);
  const streamingFrame = useRef(false);
  const frameIndexRef = useRef(0);
  const [permission, requestPermission] = useCameraPermissions();
  const [analysisSession, setAnalysisSession] = useState(session);
  const [previewUri, setPreviewUri] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<VisionCandidate[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [analysisStarted, setAnalysisStarted] = useState(Boolean(session.targetPersonId));
  const [capturedAspectRatio, setCapturedAspectRatio] = useState(3 / 4);
  const [pictureSize, setPictureSize] = useState<string | undefined>();
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraOpened, setCameraOpened] = useState(false);
  const [pendingFrame, setPendingFrame] = useState<CapturedEnrollmentFrame | null>(null);
  const [cameraFacing, setCameraFacing] = useState<'back' | 'front'>('back');

  useEffect(() => {
    if (analysisSession.state !== 'ACTIVE' || !cameraReady) {
      return;
    }

    let cancelled = false;
    async function submitTrackingFrame() {
      if (cancelled || streamingFrame.current) {
        return;
      }
      streamingFrame.current = true;
      try {
        const picture = await camera.current?.takePictureAsync({
          base64: true,
          quality: 0.25,
          shutterSound: false,
        });
        if (!picture?.base64 || cancelled) {
          return;
        }
        const nextFrame = frameIndexRef.current + 1;
        const result = await submitVisionEnrollmentFrame(endpoint, {
          sessionId: analysisSession.id,
          imageBase64: picture.base64,
          frameIndex: nextFrame,
          timestampMs: Date.now(),
        }, authorization);
        if (result.errors.length) {
          setMessage(result.errors[0].message);
          return;
        }
        frameIndexRef.current = nextFrame;
        setFrameIndex(nextFrame);
        const status = await fetchTransientSessionState(endpoint, analysisSession.id, authorization);
        if (cancelled) return;
        setMessage(status.errors[0]?.message ?? visionTrackingMessage(status.transient));
      } catch {
        if (!cancelled) {
          setMessage('Could not send the camera frame or retrieve the Vision result. Retrying…');
        }
      } finally {
        streamingFrame.current = false;
      }
    }

    void submitTrackingFrame();
    const interval = setInterval(() => void submitTrackingFrame(), 1500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [analysisSession.id, analysisSession.state, authorization, cameraReady, endpoint]);

  async function configureCamera() {
    const sizes = (await camera.current?.getAvailablePictureSizesAsync()) ?? [];
    const ranked = sizes
      .map(size => {
        const [width, height] = size.split('x').map(Number);
        return {size, pixels: width * height};
      })
      .filter(item => Number.isFinite(item.pixels))
      .sort((left, right) => right.pixels - left.pixels);
    const selected = ranked.find(item => item.pixels <= 1280 * 720) ?? ranked.at(-1);
    setPictureSize(selected?.size);
    setCameraReady(true);
  }

  async function beginEnrollment() {
    setBusy(true);
    setMessage(null);
    try {
      if (!permission?.granted) {
        const granted = await requestPermission();
        if (!granted.granted) {
          setMessage('Camera access is required to select who Vision should track.');
          return;
        }
      }
      setCameraOpened(true);
    } catch {
      setMessage('The camera could not be opened. Check the permission and try again.');
    } finally {
      setBusy(false);
    }
  }

  async function processEnrollmentFrame(picture: CapturedEnrollmentFrame) {
    setBusy(true);
    setMessage(null);
    try {
      let activeSession = analysisSession;
      if (!analysisStarted) {
        const analysisResult = await startSessionVisionAnalysis(endpoint, {
          sessionId: session.id,
          expectedRevision: session.revision,
          idempotencyKey: `enrollment-${session.id}`,
        }, authorization);
        if (!analysisResult.session) {
          setMessage(
            analysisResult.errors[0]?.message ??
              'Vision is unavailable. Your frame is ready; retry when the service reconnects.',
          );
          return;
        }
        activeSession = analysisResult.session;
        setAnalysisSession(activeSession);
        setAnalysisStarted(true);
        onSessionChange(activeSession);
      }

      const nextFrame = frameIndex + 1;
      const result = await submitVisionEnrollmentFrame(endpoint, {
        sessionId: activeSession.id,
        imageBase64: picture.base64,
        frameIndex: nextFrame,
        timestampMs: Date.now(),
      }, authorization);
      if (result.errors.length) {
        setMessage(result.errors[0].message);
        return;
      }
      setFrameIndex(nextFrame);
      frameIndexRef.current = nextFrame;
      setCandidates(result.candidates);
      if (!result.candidates.length) {
        setMessage('No person was found. Keep your full body visible and retake the frame.');
      } else if (result.candidates.length > 1) {
        setMessage('Several people were found. Tap the box around you.');
      } else {
        setMessage('One person found. Tap the highlighted box to confirm it is you.');
      }
    } catch {
      setMessage('The enrollment frame could not be processed. Try again.');
    } finally {
      setBusy(false);
    }
  }

  async function captureCandidates() {
    setBusy(true);
    setMessage(null);
    try {
      const picture = await camera.current?.takePictureAsync({base64: true, quality: 0.35});
      if (!picture?.base64) {
        setMessage('The camera did not return a usable frame. Try again.');
        return;
      }
      const captured = {
        base64: picture.base64,
        uri: picture.uri,
        width: picture.width,
        height: picture.height,
      };
      setPendingFrame(captured);
      setPreviewUri(captured.uri);
      setCapturedAspectRatio(captured.width / captured.height);
      await processEnrollmentFrame(captured);
    } catch {
      setMessage('The camera could not capture a frame. Try again.');
    } finally {
      setBusy(false);
    }
  }

  async function confirm(candidate: VisionCandidate) {
    setBusy(true);
    setMessage(null);
    try {
      const result = await confirmSessionTarget(
        endpoint,
        {
          sessionId: analysisSession.id,
          expectedRevision: analysisSession.revision,
          idempotencyKey: `target-${analysisSession.id}-${candidate.candidateId}`,
        },
        candidate.candidateId,
        authorization,
      );
      if (!result.session) {
        setMessage(result.errors[0]?.message ?? 'Target confirmation failed.');
        return;
      }
      await activateSession(result.session);
    } catch {
      setMessage('Target confirmation failed. Try again.');
    } finally {
      setBusy(false);
    }
  }

  async function activateSession(confirmedSession: PreparedSession) {
    const started = await startSession(endpoint, {
      sessionId: confirmedSession.id,
      expectedRevision: confirmedSession.revision,
      idempotencyKey: `start-${confirmedSession.id}`,
    }, authorization);
    if (!started.session) {
      setAnalysisSession(confirmedSession);
      onSessionChange(confirmedSession);
      setMessage(started.errors[0]?.message ?? 'Target confirmed, but the workout could not start.');
      return;
    }
    const activeSession = {
      ...started.session,
      targetPersonId: started.session.targetPersonId ?? confirmedSession.targetPersonId,
    };
    setAnalysisSession(activeSession);
    onSessionChange(activeSession);
    setPreviewUri(null);
    setPendingFrame(null);
    setCandidates([]);
    setCameraReady(false);
    setMessage('Workout started. Preparing live body tracking…');
  }

  if (analysisSession.targetPersonId && analysisSession.state !== 'ACTIVE') {
    return (
      <View style={styles.card} testID="target-enrollment-confirmed">
        <Text style={styles.eyebrow}>VISION TARGET</Text>
        <Text style={styles.confirmed}>Target confirmed</Text>
        <Text style={styles.help}>Other people and animals are excluded from session progress.</Text>
        <ActionButton
          disabled={busy}
          label={busy ? 'Starting workout…' : 'Start workout'}
          onPress={() => {
            setBusy(true);
            setMessage(null);
            void activateSession(analysisSession).finally(() => setBusy(false));
          }}
        />
        {message ? <Text style={styles.message}>{message}</Text> : null}
      </View>
    );
  }

  if (analysisSession.state === 'ACTIVE') {
    return (
      <View style={styles.card} testID="vision-tracking-active">
        <Text style={styles.eyebrow}>LIVE VISION</Text>
        <Text style={styles.confirmed}>Workout active</Text>
        <Text style={styles.help}>Only your confirmed target is evaluated. Keep this screen open.</Text>
        <CameraView
          animateShutter={false}
          flash="off"
          facing={cameraFacing}
          onCameraReady={() => void configureCamera()}
          pictureSize={pictureSize}
          ref={camera}
          style={styles.cameraPreview}
        >
          <Pressable
            accessibilityLabel={`Use ${cameraFacing === 'back' ? 'front' : 'back'} camera`}
            onPress={() => {
              setCameraReady(false);
              setPictureSize(undefined);
              setCameraFacing(current => (current === 'back' ? 'front' : 'back'));
            }}
            style={({pressed}) => [styles.flipButton, pressed && styles.flipButtonPressed]}
          >
            <Text style={styles.flipButtonText}>Flip camera</Text>
          </Pressable>
          <View pointerEvents="none" style={styles.guide} />
        </CameraView>
        <Text style={styles.message}>
          {message ?? (cameraReady ? `Tracking frame ${frameIndex}` : 'Preparing camera…')}
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.card} testID="target-enrollment-card">
      <Text style={styles.eyebrow}>VISION TARGET</Text>
      <Text style={styles.title}>Choose who Vision should track</Text>
      <Text style={styles.help}>
        This frame is used only for this session enrollment and is not saved as a progress photo.
      </Text>

      {!cameraOpened ? (
        <ActionButton
          disabled={busy}
          label={busy ? 'Starting…' : 'Open camera'}
          onPress={beginEnrollment}
        />
      ) : previewUri ? (
        <View style={[styles.previewWrap, {aspectRatio: capturedAspectRatio}]}>
          <Image resizeMode="cover" source={{uri: previewUri}} style={styles.capturedPreview} />
          {candidates.map(candidate => (
            <Pressable
              accessibilityLabel={`Select person ${candidate.candidateId}`}
              key={candidate.candidateId}
              onPress={() => confirm(candidate)}
              style={[
                styles.candidateBox,
                {
                  left: `${candidate.bbox[0] * 100}%`,
                  top: `${candidate.bbox[1] * 100}%`,
                  width: `${candidate.bbox[2] * 100}%`,
                  height: `${candidate.bbox[3] * 100}%`,
                },
              ]}
              testID={`candidate-${candidate.candidateId}`}
            >
              <Text style={styles.confidence}>{Math.round(candidate.confidence * 100)}%</Text>
            </Pressable>
          ))}
        </View>
      ) : (
        <CameraView
          facing={cameraFacing}
          onCameraReady={() => void configureCamera()}
          pictureSize={pictureSize}
          ref={camera}
          style={styles.cameraPreview}
        >
          <Pressable
            accessibilityLabel={`Use ${cameraFacing === 'back' ? 'front' : 'back'} camera`}
            disabled={busy}
            onPress={() => {
              setCameraReady(false);
              setPictureSize(undefined);
              setCameraFacing(current => (current === 'back' ? 'front' : 'back'));
            }}
            style={({pressed}) => [styles.flipButton, pressed && styles.flipButtonPressed]}
          >
            <Text style={styles.flipButtonText}>Flip camera</Text>
          </Pressable>
          <View pointerEvents="none" style={styles.guide} />
        </CameraView>
      )}

      {cameraOpened ? (
        <ActionButton
          disabled={busy || (!previewUri && !cameraReady)}
          label={
            busy
              ? 'Processing…'
              : previewUri && !analysisStarted
                ? 'Retry Vision'
                : previewUri
                  ? 'Retake frame'
                : cameraReady
                  ? 'Capture enrollment frame'
                  : 'Preparing camera…'
          }
          onPress={() => {
            if (previewUri && !analysisStarted && pendingFrame) {
              void processEnrollmentFrame(pendingFrame);
            } else if (previewUri) {
              setPreviewUri(null);
              setPendingFrame(null);
              setCandidates([]);
              setMessage(null);
              setCameraReady(false);
            } else {
              void captureCandidates();
            }
          }}
        />
      ) : null}
      {message ? <Text style={styles.message}>{message}</Text> : null}
    </View>
  );
}

function ActionButton({disabled, label, onPress}: {disabled: boolean; label: string; onPress: () => void}) {
  return (
    <Pressable disabled={disabled} onPress={onPress} style={[styles.button, disabled && styles.disabled]}>
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {backgroundColor: '#111827', borderColor: '#293244', borderRadius: 18, borderWidth: 1, marginTop: 20, padding: 16},
  eyebrow: {color: '#A3FF12', fontSize: 10, fontWeight: '800', letterSpacing: 1.5},
  title: {color: '#F4F7FB', fontSize: 20, fontWeight: '700', marginTop: 8},
  confirmed: {color: '#A3FF12', fontSize: 18, fontWeight: '700', marginTop: 8},
  help: {color: '#9CA3AF', fontSize: 13, lineHeight: 19, marginTop: 6},
  previewWrap: {borderRadius: 14, marginTop: 16, overflow: 'hidden', position: 'relative', width: '100%'},
  capturedPreview: {height: '100%', width: '100%'},
  cameraPreview: {borderRadius: 14, height: 360, marginTop: 16, overflow: 'hidden', width: '100%'},
  flipButton: {backgroundColor: 'rgba(7, 11, 20, 0.82)', borderColor: '#A3FF12', borderRadius: 999, borderWidth: 1, paddingHorizontal: 14, paddingVertical: 9, position: 'absolute', right: 12, top: 12, zIndex: 1},
  flipButtonPressed: {opacity: 0.72},
  flipButtonText: {color: '#F4F7FB', fontSize: 12, fontWeight: '800'},
  guide: {alignSelf: 'center', borderColor: '#A3FF12', borderRadius: 120, borderWidth: 2, height: 300, marginTop: 28, width: '72%'},
  candidateBox: {borderColor: '#A3FF12', borderWidth: 3, position: 'absolute'},
  confidence: {alignSelf: 'flex-start', backgroundColor: '#A3FF12', color: '#070B14', fontSize: 11, fontWeight: '800', paddingHorizontal: 5, paddingVertical: 2},
  button: {alignItems: 'center', backgroundColor: '#A3FF12', borderRadius: 12, marginTop: 16, padding: 14},
  buttonText: {color: '#070B14', fontSize: 14, fontWeight: '800'},
  disabled: {opacity: 0.5},
  message: {color: '#D1D5DB', fontSize: 13, lineHeight: 19, marginTop: 12},
});

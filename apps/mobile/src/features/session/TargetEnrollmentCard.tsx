import {
  confirmSessionTarget,
  startSessionVisionAnalysis,
  submitVisionEnrollmentFrame,
  type PreparedSession,
  type VisionCandidate,
} from '@kinetiq/session-client';
import {CameraView, useCameraPermissions} from 'expo-camera';
import {useRef, useState} from 'react';
import {Image, Pressable, StyleSheet, Text, View} from 'react-native';

interface Props {
  endpoint: string;
  session: PreparedSession;
  onSessionChange: (session: PreparedSession) => void;
}

export function TargetEnrollmentCard({endpoint, session, onSessionChange}: Props) {
  const camera = useRef<CameraView>(null);
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
      const result = await startSessionVisionAnalysis(endpoint, {
        sessionId: session.id,
        expectedRevision: session.revision,
        idempotencyKey: `enrollment-${session.id}`,
      });
      if (!result.session) {
        setMessage(result.errors[0]?.message ?? 'Could not start Vision enrollment.');
        return;
      }
      setAnalysisSession(result.session);
      setAnalysisStarted(true);
      onSessionChange(result.session);
    } catch {
      setMessage('Could not reach Vision. Check the connection and try again.');
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
      const nextFrame = frameIndex + 1;
      const result = await submitVisionEnrollmentFrame(endpoint, {
        sessionId: analysisSession.id,
        imageBase64: picture.base64,
        frameIndex: nextFrame,
        timestampMs: Date.now(),
      });
      if (result.errors.length) {
        setMessage(result.errors[0].message);
        return;
      }
      setFrameIndex(nextFrame);
      setPreviewUri(picture.uri);
      setCapturedAspectRatio(picture.width / picture.height);
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
      );
      if (!result.session) {
        setMessage(result.errors[0]?.message ?? 'Target confirmation failed.');
        return;
      }
      setAnalysisSession(result.session);
      onSessionChange(result.session);
      setMessage('Target confirmed. Only this person will count toward the session.');
    } catch {
      setMessage('Target confirmation failed. Try again.');
    } finally {
      setBusy(false);
    }
  }

  if (analysisSession.targetPersonId) {
    return (
      <View style={styles.card} testID="target-enrollment-confirmed">
        <Text style={styles.eyebrow}>VISION TARGET</Text>
        <Text style={styles.confirmed}>Target confirmed</Text>
        <Text style={styles.help}>Other people and animals are excluded from session progress.</Text>
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

      {!analysisStarted ? (
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
          facing="back"
          onCameraReady={() => void configureCamera()}
          pictureSize={pictureSize}
          ref={camera}
          style={styles.cameraPreview}
        >
          <View style={styles.guide} />
        </CameraView>
      )}

      {analysisStarted ? (
        <ActionButton
          disabled={busy || (!previewUri && !cameraReady)}
          label={
            busy
              ? 'Processing…'
              : previewUri
                ? 'Retake frame'
                : cameraReady
                  ? 'Capture enrollment frame'
                  : 'Preparing camera…'
          }
          onPress={() => {
            if (previewUri) {
              setPreviewUri(null);
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
  guide: {alignSelf: 'center', borderColor: '#A3FF12', borderRadius: 120, borderWidth: 2, height: 300, marginTop: 28, width: '72%'},
  candidateBox: {borderColor: '#A3FF12', borderWidth: 3, position: 'absolute'},
  confidence: {alignSelf: 'flex-start', backgroundColor: '#A3FF12', color: '#070B14', fontSize: 11, fontWeight: '800', paddingHorizontal: 5, paddingVertical: 2},
  button: {alignItems: 'center', backgroundColor: '#A3FF12', borderRadius: 12, marginTop: 16, padding: 14},
  buttonText: {color: '#070B14', fontSize: 14, fontWeight: '800'},
  disabled: {opacity: 0.5},
  message: {color: '#D1D5DB', fontSize: 13, lineHeight: 19, marginTop: 12},
});

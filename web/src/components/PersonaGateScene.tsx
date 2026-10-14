import { Canvas, useFrame } from '@react-three/fiber'
import {
  Environment,
  Float,
  MeshDistortMaterial,
  OrbitControls,
  Sparkles,
  Stars,
  Text,
} from '@react-three/drei'
import { Bloom, EffectComposer, Vignette } from '@react-three/postprocessing'
import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import * as THREE from 'three'
import type { DeskPersona } from '../hooks/usePersona'

const VOID = '#02040a'
const CYAN = '#5ee9f2'
const LIME = '#8ef0a8'
const MAGENTA = '#ff4d9a'
const AMBER = '#ffc45c'

type Pick = DeskPersona | null

function useHoverScale(active: boolean, reduce: boolean) {
  const ref = useRef<THREE.Group>(null)
  useFrame((_, dt) => {
    const g = ref.current
    if (!g) return
    const target = active ? 1.08 : 1
    const s = THREE.MathUtils.lerp(g.scale.x, target, reduce ? 1 : 1 - Math.pow(0.001, dt))
    g.scale.setScalar(s)
  })
  return ref
}

function AlienMesas() {
  const geom = useMemo(() => {
    const g = new THREE.PlaneGeometry(28, 18, 48, 32)
    const pos = g.attributes.position as THREE.BufferAttribute
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i)
      const y = pos.getY(i)
      const ridge =
        Math.sin(x * 0.35) * 0.9 +
        Math.cos(y * 0.28) * 0.7 +
        Math.sin((x + y) * 0.22) * 0.5
      const peak = Math.max(0, ridge) ** 1.6
      pos.setZ(i, peak * 2.2 - 1.4)
    }
    g.computeVertexNormals()
    return g
  }, [])

  return (
    <mesh geometry={geom} rotation={[-Math.PI / 2.05, 0, 0.15]} position={[0, -2.8, -4]}>
      <meshStandardMaterial
        color="#0a1424"
        emissive="#1a3050"
        emissiveIntensity={0.35}
        metalness={0.65}
        roughness={0.42}
        flatShading
      />
    </mesh>
  )
}

function NebulaVeil() {
  return (
    <>
      <mesh position={[-6, 1.5, -12]} rotation={[0, 0.4, 0]}>
        <planeGeometry args={[22, 14]} />
        <MeshDistortMaterial
          color="#2a1848"
          emissive={MAGENTA}
          emissiveIntensity={0.55}
          transparent
          opacity={0.22}
          distort={0.35}
          speed={1.2}
          roughness={1}
        />
      </mesh>
      <mesh position={[7, 2, -14]} rotation={[0, -0.35, 0]}>
        <planeGeometry args={[20, 12]} />
        <MeshDistortMaterial
          color="#0e2840"
          emissive={CYAN}
          emissiveIntensity={0.45}
          transparent
          opacity={0.18}
          distort={0.28}
          speed={0.9}
          roughness={1}
        />
      </mesh>
    </>
  )
}

function DistantOrbs() {
  const orbs = useMemo(
    () =>
      [
        { p: [-9, 4, -18] as const, c: CYAN, s: 0.9 },
        { p: [10, 5.5, -20] as const, c: AMBER, s: 1.1 },
        { p: [0, 7, -22] as const, c: MAGENTA, s: 0.65 },
      ] as const,
    [],
  )
  return (
    <>
      {orbs.map((o) => (
        <mesh key={o.p.join()} position={o.p}>
          <sphereGeometry args={[o.s, 24, 24]} />
          <meshBasicMaterial color={o.c} transparent opacity={0.35} />
        </mesh>
      ))}
    </>
  )
}

function ObserverPersona({
  active,
  onPick,
  onHoverIn,
  reduce,
}: {
  active: boolean
  onPick: () => void
  onHoverIn: () => void
  reduce: boolean
}) {
  const root = useHoverScale(active, reduce)
  const dome = useRef<THREE.Mesh>(null)
  const scope = useRef<THREE.Group>(null)

  useFrame((state, dt) => {
    if (reduce) return
    if (dome.current) dome.current.rotation.y += dt * 0.12
    if (scope.current) scope.current.rotation.z = Math.sin(state.clock.elapsedTime * 0.7) * 0.08
  })

  return (
    <group
      ref={root}
      position={[-4.2, 0.2, 0]}
      onClick={(e) => {
        e.stopPropagation()
        onPick()
      }}
      onPointerOver={() => {
        onHoverIn()
        document.body.style.cursor = 'pointer'
      }}
      onPointerOut={() => {
        document.body.style.cursor = 'auto'
      }}
    >
      <Float speed={1.2} rotationIntensity={0.08} floatIntensity={0.35}>
        <mesh position={[0, -0.55, 0]}>
          <cylinderGeometry args={[1.65, 2.1, 0.35, 6]} />
          <meshStandardMaterial color="#141e2e" metalness={0.8} roughness={0.25} emissive={CYAN} emissiveIntensity={active ? 0.45 : 0.15} />
        </mesh>
        <mesh position={[0, -0.35, 0]}>
          <torusGeometry args={[1.72, 0.04, 12, 48]} />
          <meshStandardMaterial color={CYAN} emissive={CYAN} emissiveIntensity={1.2} metalness={1} roughness={0.2} />
        </mesh>

        <group position={[0, 0.35, 0]}>
          <mesh position={[0, -0.15, 0]}>
            <capsuleGeometry args={[0.28, 0.55, 8, 16]} />
            <meshStandardMaterial color="#1c2838" metalness={0.5} roughness={0.4} />
          </mesh>
          <mesh position={[0, 0.55, 0]}>
            <sphereGeometry args={[0.32, 24, 24]} />
            <meshStandardMaterial color="#243044" metalness={0.55} roughness={0.35} />
          </mesh>
          <mesh ref={dome} position={[0, 0.55, 0]}>
            <sphereGeometry args={[0.52, 32, 32, 0, Math.PI * 2, 0, Math.PI / 2]} />
            <meshPhysicalMaterial
              color={CYAN}
              transmission={0.85}
              thickness={0.4}
              roughness={0.05}
              metalness={0.1}
              emissive={LIME}
              emissiveIntensity={active ? 0.8 : 0.25}
              transparent
              opacity={0.75}
            />
          </mesh>
        </group>

        <group ref={scope} position={[0.85, 0.45, 0.35]} rotation={[0.35, -0.5, 0]}>
          <mesh rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.06, 0.08, 0.9, 12]} />
            <meshStandardMaterial color="#8899aa" metalness={0.9} roughness={0.15} />
          </mesh>
          <mesh position={[0, 0, 0.55]}>
            <cylinderGeometry args={[0.14, 0.14, 0.35, 16]} />
            <meshStandardMaterial color="#2a3848" emissive={LIME} emissiveIntensity={0.6} metalness={0.7} roughness={0.2} />
          </mesh>
        </group>

        <Sparkles count={active ? 36 : 18} scale={2.4} size={2} speed={reduce ? 0 : 0.35} color={LIME} opacity={0.5} />
      </Float>
      <Text position={[0, 2.35, 0]} fontSize={0.28} color={LIME} anchorX="center" anchorY="middle" maxWidth={3.2}>
        Space Observer
      </Text>
      <Text position={[0, 1.95, 0]} fontSize={0.14} color="#9eb8c8" anchorX="center" anchorY="middle" maxWidth={3.4}>
        Swing · screens · digest
      </Text>
    </group>
  )
}

function SpacemanPersona({
  active,
  onPick,
  onHoverIn,
  reduce,
}: {
  active: boolean
  onPick: () => void
  onHoverIn: () => void
  reduce: boolean
}) {
  const root = useHoverScale(active, reduce)
  const jet = useRef<THREE.Group>(null)

  useFrame((state) => {
    if (reduce) return
    if (jet.current) {
      jet.current.rotation.z = Math.sin(state.clock.elapsedTime * 2.2) * 0.06
      jet.current.position.y = 0.35 + Math.sin(state.clock.elapsedTime * 1.8) * 0.06
    }
  })

  return (
    <group
      ref={root}
      position={[4.2, 0.2, 0]}
      onClick={(e) => {
        e.stopPropagation()
        onPick()
      }}
      onPointerOver={() => {
        onHoverIn()
        document.body.style.cursor = 'pointer'
      }}
      onPointerOut={() => {
        document.body.style.cursor = 'auto'
      }}
    >
      <Float speed={2.4} rotationIntensity={0.15} floatIntensity={0.55}>
        <mesh position={[0, -0.55, 0]}>
          <cylinderGeometry args={[1.65, 2.1, 0.35, 6]} />
          <meshStandardMaterial color="#141e2e" metalness={0.8} roughness={0.25} emissive={MAGENTA} emissiveIntensity={active ? 0.5 : 0.12} />
        </mesh>
        <mesh position={[0, -0.35, 0]}>
          <torusGeometry args={[1.72, 0.04, 12, 48]} />
          <meshStandardMaterial color={MAGENTA} emissive={MAGENTA} emissiveIntensity={1.3} metalness={1} roughness={0.2} />
        </mesh>

        <group ref={jet} position={[0, 0.35, 0]}>
          <mesh rotation={[0.15, 0, 0]}>
            <capsuleGeometry args={[0.32, 0.65, 8, 16]} />
            <meshStandardMaterial color="#e8eef4" metalness={0.35} roughness={0.45} />
          </mesh>
          <mesh position={[0, 0.72, 0.05]}>
            <sphereGeometry args={[0.36, 28, 28]} />
            <meshPhysicalMaterial
              color="#c8f0ff"
              metalness={0.2}
              roughness={0.08}
              transmission={0.55}
              thickness={0.25}
              emissive={CYAN}
              emissiveIntensity={active ? 0.9 : 0.35}
            />
          </mesh>
          <mesh position={[-0.38, 0.15, -0.15]} rotation={[0, 0, 0.8]}>
            <boxGeometry args={[0.12, 0.55, 0.28]} />
            <meshStandardMaterial color="#8899aa" metalness={0.85} roughness={0.2} />
          </mesh>
          <mesh position={[0.38, 0.15, -0.15]} rotation={[0, 0, -0.8]}>
            <boxGeometry args={[0.12, 0.55, 0.28]} />
            <meshStandardMaterial color="#8899aa" metalness={0.85} roughness={0.2} />
          </mesh>
          <group position={[0, 0.05, -0.42]}>
            <mesh>
              <boxGeometry args={[0.55, 0.7, 0.35]} />
              <meshStandardMaterial color="#556677" emissive={MAGENTA} emissiveIntensity={0.4} metalness={0.75} roughness={0.25} />
            </mesh>
            <pointLight color={MAGENTA} intensity={active ? 12 : 4} distance={3} />
            <Sparkles count={active ? 42 : 20} scale={1.2} size={3} speed={reduce ? 0 : 1.2} color={MAGENTA} position={[0, -0.5, -0.2]} />
          </group>
        </group>
      </Float>
      <Text position={[0, 2.35, 0]} fontSize={0.28} color={MAGENTA} anchorX="center" anchorY="middle" maxWidth={3.2}>
        Spaceman
      </Text>
      <Text position={[0, 1.95, 0]} fontSize={0.14} color="#9eb8c8" anchorX="center" anchorY="middle" maxWidth={3.4}>
        Flow · OI · CVD · ops
      </Text>
    </group>
  )
}

function BridgeArc() {
  const geom = useMemo(() => {
    const curve = new THREE.QuadraticBezierCurve3(
      new THREE.Vector3(-2.2, 1.2, -0.5),
      new THREE.Vector3(0, 2.8, -1.5),
      new THREE.Vector3(2.2, 1.2, -0.5),
    )
    return new THREE.TubeGeometry(curve, 64, 0.025, 8, false)
  }, [])
  useEffect(() => () => geom.dispose(), [geom])
  return (
    <mesh geometry={geom}>
      <meshStandardMaterial color={AMBER} emissive={AMBER} emissiveIntensity={0.85} metalness={1} roughness={0.2} transparent opacity={0.7} />
    </mesh>
  )
}

function GateWorld({
  hover,
  reduce,
  onHover,
  onSelect,
}: {
  hover: Pick
  reduce: boolean
  onHover: (p: Pick) => void
  onSelect: (p: DeskPersona) => void
}) {
  return (
    <>
      <ambientLight intensity={0.22} />
      <pointLight position={[0, 6, 4]} intensity={35} color="#eef8ff" distance={28} />
      <pointLight position={[-6, 2, 2]} intensity={22} color={CYAN} distance={18} />
      <pointLight position={[6, 2, 2]} intensity={22} color={MAGENTA} distance={18} />
      <Stars radius={80} depth={50} count={3200} factor={3} saturation={0.5} fade speed={reduce ? 0 : 0.4} />
      <Sparkles count={80} scale={18} size={2.5} speed={reduce ? 0 : 0.25} opacity={0.35} color={CYAN} />
      <NebulaVeil />
      <DistantOrbs />
      <AlienMesas />
      <BridgeArc />
      <group
        onPointerMissed={() => onHover(null)}
        onPointerOver={(e) => {
          e.stopPropagation()
        }}
      >
        <ObserverPersona
          active={hover === 'observer'}
          reduce={reduce}
          onHoverIn={() => onHover('observer')}
          onPick={() => onSelect('observer')}
        />
        <SpacemanPersona
          active={hover === 'spaceman'}
          reduce={reduce}
          onHoverIn={() => onHover('spaceman')}
          onPick={() => onSelect('spaceman')}
        />
      </group>
      <EffectComposer multisampling={0}>
        <Bloom luminanceThreshold={0.35} luminanceSmoothing={0.85} intensity={0.85} />
        <Vignette eskil={false} offset={0.18} darkness={0.65} />
      </EffectComposer>
    </>
  )
}

function SceneInner({
  onSelect,
}: {
  onSelect: (p: DeskPersona) => void
}) {
  const [hover, setHover] = useState<Pick>(null)
  const reduce = useMemo(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  }, [])

  return (
    <>
      <color attach="background" args={[VOID]} />
      <fog attach="fog" args={[VOID, 8, 32]} />
      <Suspense fallback={null}>
        <Environment preset="night" />
      </Suspense>
      <GateWorld hover={hover} reduce={reduce} onHover={setHover} onSelect={onSelect} />
      <OrbitControls
        enablePan={false}
        minDistance={7}
        maxDistance={16}
        minPolarAngle={Math.PI / 4}
        maxPolarAngle={Math.PI / 2.05}
        autoRotate={!reduce}
        autoRotateSpeed={0.35}
        enableDamping
        dampingFactor={0.06}
      />
    </>
  )
}

export function PersonaGateScene({ onSelect }: { onSelect: (p: DeskPersona) => void }) {
  const [ready, setReady] = useState(false)

  return (
    <div className="relative h-full w-full overflow-hidden universe-frame persona-gate-frame">
      {!ready && (
        <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center universe-boot">
          <p className="hud-kicker">Loading mission deck…</p>
        </div>
      )}
      <Canvas
        camera={{ position: [0, 2.2, 10.5], fov: 38 }}
        dpr={[1, 1.75]}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
        onCreated={({ gl }) => {
          gl.setClearColor(VOID, 1)
          gl.toneMapping = THREE.ACESFilmicToneMapping
          gl.toneMappingExposure = 1.08
          setReady(true)
        }}
      >
        <SceneInner onSelect={onSelect} />
      </Canvas>
    </div>
  )
}

export function PersonaGateOverlay({
  open,
  onClose,
  onSelect,
}: {
  open: boolean
  onClose: () => void
  onSelect: (p: DeskPersona) => void
  children?: ReactNode
}) {
  if (!open) return null

  return (
    <div
      className="persona-gate-overlay fixed inset-0 z-[100] flex flex-col bg-void/95 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="persona-gate-title"
    >
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line/40 px-4 py-3 sm:px-8">
        <div>
          <p className="font-mono text-xs uppercase tracking-wide text-cyan">Mission deck</p>
          <h2 id="persona-gate-title" className="font-display text-xl font-bold text-ink sm:text-2xl">
            Choose your crew
          </h2>
        </div>
        <button type="button" className="btn" onClick={onClose}>
          Back to Orbis
        </button>
      </div>
      <p className="pointer-events-none px-4 pb-2 text-center text-sm text-muted sm:px-8">
        Click a persona to enter their module path · signal-only · never orders
      </p>
      <div className="min-h-0 flex-1 px-2 pb-4 sm:px-6 sm:pb-6">
        <PersonaGateScene onSelect={onSelect} />
      </div>
    </div>
  )
}

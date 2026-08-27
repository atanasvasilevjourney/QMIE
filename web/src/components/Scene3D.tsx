import { Canvas, useFrame } from '@react-three/fiber'
import {
  Float,
  Grid,
  MeshDistortMaterial,
  OrbitControls,
  Sparkles,
  Stars,
} from '@react-three/drei'
import { Bloom, EffectComposer, Noise, Vignette } from '@react-three/postprocessing'
import { useMemo, useRef, useState, type ReactNode } from 'react'
import * as THREE from 'three'
import type { RadarSnapshot } from '../types'

const CYAN = '#00f0ff'
const MAGENTA = '#ff2bd6'
const LIME = '#b8ff3c'
const AMBER = '#ffb020'
const VOID = '#03040a'

function mixRadarColor(green: number, grey: number, red: number) {
  const total = Math.max(1, green + grey + red)
  const g = green / total
  const r = red / total
  const gy = grey / total
  return new THREE.Color().setRGB(
    0.12 + r * 0.88 + gy * 0.25,
    0.25 + g * 0.7 + gy * 0.2,
    0.85 - r * 0.45 + g * 0.1,
  )
}

function HoloCore({ green, grey, red }: { green: number; grey: number; red: number }) {
  const mesh = useRef<THREE.Mesh>(null)
  const inner = useRef<THREE.Mesh>(null)
  const color = useMemo(() => mixRadarColor(green, grey, red), [green, grey, red])

  useFrame((state, dt) => {
    if (mesh.current) {
      mesh.current.rotation.y += dt * 0.32
      mesh.current.rotation.x += dt * 0.1
      const pulse = 1.28 + Math.sin(state.clock.elapsedTime * 1.6) * 0.04
      mesh.current.scale.setScalar(pulse)
    }
    if (inner.current) {
      inner.current.rotation.y -= dt * 0.55
      inner.current.rotation.z += dt * 0.2
    }
  })

  return (
    <group>
      <mesh ref={mesh}>
        <icosahedronGeometry args={[1, 3]} />
        <MeshDistortMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.85}
          roughness={0.12}
          metalness={0.95}
          distort={0.32}
          speed={2.4}
          transparent
          opacity={0.88}
        />
      </mesh>
      <mesh ref={inner} scale={0.55}>
        <octahedronGeometry args={[1, 0]} />
        <meshStandardMaterial
          color={AMBER}
          emissive={AMBER}
          emissiveIntensity={1.4}
          metalness={1}
          roughness={0.15}
          wireframe
        />
      </mesh>
    </group>
  )
}

function WireShell() {
  const ref = useRef<THREE.Mesh>(null)
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.y -= dt * 0.14
  })
  return (
    <mesh ref={ref} scale={1.78}>
      <icosahedronGeometry args={[1, 1]} />
      <meshBasicMaterial color={CYAN} wireframe transparent opacity={0.28} />
    </mesh>
  )
}

function NeonRings() {
  const a = useRef<THREE.Mesh>(null)
  const b = useRef<THREE.Mesh>(null)
  const c = useRef<THREE.Mesh>(null)
  useFrame((state, dt) => {
    const t = state.clock.elapsedTime
    if (a.current) {
      a.current.rotation.x += dt * 0.35
      a.current.rotation.z = Math.sin(t * 0.4) * 0.2
    }
    if (b.current) {
      b.current.rotation.y -= dt * 0.28
      b.current.rotation.x = 0.5 + Math.cos(t * 0.3) * 0.15
    }
    if (c.current) {
      c.current.rotation.z += dt * 0.22
      c.current.rotation.y = Math.sin(t * 0.25) * 0.35
    }
  })
  return (
    <group>
      <mesh ref={a}>
        <torusGeometry args={[2.05, 0.018, 16, 128]} />
        <meshBasicMaterial color={MAGENTA} transparent opacity={0.85} />
      </mesh>
      <mesh ref={b}>
        <torusGeometry args={[2.4, 0.012, 16, 160]} />
        <meshBasicMaterial color={CYAN} transparent opacity={0.65} />
      </mesh>
      <mesh ref={c}>
        <torusGeometry args={[2.75, 0.008, 12, 180]} />
        <meshBasicMaterial color={LIME} transparent opacity={0.35} />
      </mesh>
    </group>
  )
}

const COIN_LABELS = ['PEPE', 'DOGE', 'WIF', 'BONK', 'BTC', 'ETH', 'SOL', 'ORDI', 'MEME', 'QMIE']

function MemeCoin({
  color,
  label,
  scale = 1,
}: {
  color: string
  label: string
  scale?: number
}) {
  const emboss = useMemo(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 256
    canvas.height = 256
    const ctx = canvas.getContext('2d')!
    const grd = ctx.createRadialGradient(128, 128, 20, 128, 128, 120)
    grd.addColorStop(0, '#ffffff')
    grd.addColorStop(0.45, color)
    grd.addColorStop(1, '#1a1020')
    ctx.fillStyle = grd
    ctx.beginPath()
    ctx.arc(128, 128, 118, 0, Math.PI * 2)
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.55)'
    ctx.lineWidth = 8
    ctx.stroke()
    ctx.fillStyle = '#05060a'
    ctx.font = 'bold 54px Syne, IBM Plex Sans, sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(label.slice(0, 4), 128, 128)
    const tex = new THREE.CanvasTexture(canvas)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }, [color, label])

  return (
    <mesh scale={scale} rotation={[Math.PI / 2, 0, 0]}>
      <cylinderGeometry args={[0.22, 0.22, 0.045, 32]} />
      <meshStandardMaterial
        map={emboss}
        emissive={color}
        emissiveIntensity={0.45}
        metalness={0.95}
        roughness={0.22}
      />
    </mesh>
  )
}

function TokenOrbit({
  count,
  radius,
  speed,
  y,
  tilt,
}: {
  count: number
  radius: number
  speed: number
  y: number
  tilt: number
}) {
  const group = useRef<THREE.Group>(null)
  const n = Math.min(18, Math.max(8, count))
  const tokens = useMemo(
    () =>
      Array.from({ length: n }, (_, i) => {
        const a = (i / n) * Math.PI * 2
        return {
          x: Math.cos(a) * radius,
          z: Math.sin(a) * radius,
          label: COIN_LABELS[i % COIN_LABELS.length],
          color: i % 3 === 0 ? AMBER : i % 3 === 1 ? CYAN : MAGENTA,
        }
      }),
    [n, radius],
  )

  useFrame((_, dt) => {
    if (group.current) group.current.rotation.y += dt * speed
  })

  return (
    <group ref={group} position={[0, y, 0]} rotation={[tilt, 0, 0.15]}>
      {tokens.map((t, i) => (
        <Float key={i} speed={1.2 + (i % 4) * 0.25} floatIntensity={0.45} rotationIntensity={0.55}>
          <group position={[t.x, 0, t.z]}>
            <MemeCoin color={t.color} label={t.label} scale={0.95 + (i % 3) * 0.08} />
          </group>
        </Float>
      ))}
    </group>
  )
}

function EnergyBeams() {
  const group = useRef<THREE.Group>(null)
  useFrame((state) => {
    if (group.current) group.current.rotation.y = state.clock.elapsedTime * 0.15
  })
  return (
    <group ref={group}>
      {[0, 1, 2, 3, 4, 5].map((i) => {
        const a = (i / 6) * Math.PI * 2
        return (
          <mesh key={i} position={[Math.cos(a) * 3.4, 0, Math.sin(a) * 3.4]} rotation={[0, -a, 0]}>
            <boxGeometry args={[0.02, 3.2, 0.02]} />
            <meshBasicMaterial color={i % 2 ? CYAN : MAGENTA} transparent opacity={0.35} />
          </mesh>
        )
      })}
    </group>
  )
}

function SymbolNebula({ radar }: { radar: RadarSnapshot | null }) {
  const points = useRef<THREE.Points>(null)
  const { positions, colors, sizes } = useMemo(() => {
    const rows = radar?.rows?.slice(0, 220) ?? []
    // Keep a vivid cloud even when radar is empty (geo-block) — tinted chrome, not fake G/R counts.
    const n = Math.max(rows.length, 140)
    const pos = new Float32Array(n * 3)
    const col = new Float32Array(n * 3)
    const sz = new Float32Array(n)
    for (let i = 0; i < n; i++) {
      const row = rows[i]
      const shell = 3.1 + (i % 9) * 0.22 + (i % 5) * 0.05
      const a = (i / n) * Math.PI * 2 + (i % 7) * 0.07
      const y = Math.sin(i * 0.37) * 1.35 + ((i % 13) - 6) * 0.08
      pos[i * 3] = Math.cos(a) * shell
      pos[i * 3 + 1] = y
      pos[i * 3 + 2] = Math.sin(a) * shell
      const c =
        row?.color === 'GREEN'
          ? [0.15, 1, 0.42]
          : row?.color === 'RED'
            ? [1, 0.18, 0.48]
            : row?.color === 'GREY'
              ? [0.55, 0.62, 0.82]
              : [
                  0.35 + (i % 5) * 0.08,
                  0.55 + (i % 3) * 0.1,
                  0.85 + (i % 4) * 0.04,
                ]
      col[i * 3] = c[0]
      col[i * 3 + 1] = c[1]
      col[i * 3 + 2] = c[2]
      sz[i] = 0.06 + (i % 5) * 0.02
    }
    return { positions: pos, colors: col, sizes: sz }
  }, [radar])

  useFrame((_, dt) => {
    if (points.current) {
      points.current.rotation.y += dt * 0.06
      points.current.rotation.x = Math.sin(performance.now() * 0.00015) * 0.08
    }
  })

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
        <bufferAttribute attach="attributes-size" args={[sizes, 1]} />
      </bufferGeometry>
      <pointsMaterial
        size={0.09}
        vertexColors
        transparent
        opacity={0.92}
        sizeAttenuation
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  )
}

function DataFloor() {
  return (
    <group position={[0, -2.35, 0]}>
      <Grid
        args={[16, 16]}
        cellSize={0.45}
        cellThickness={0.6}
        cellColor="#00f0ff"
        sectionSize={2.25}
        sectionThickness={1.2}
        sectionColor="#ff2bd6"
        fadeDistance={18}
        fadeStrength={1.2}
        infiniteGrid
      />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]}>
        <circleGeometry args={[4.8, 64]} />
        <meshBasicMaterial color={CYAN} transparent opacity={0.04} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <ringGeometry args={[4.2, 4.35, 96]} />
        <meshBasicMaterial color={MAGENTA} transparent opacity={0.35} side={THREE.DoubleSide} />
      </mesh>
    </group>
  )
}

function Rig({ children }: { children: ReactNode }) {
  const group = useRef<THREE.Group>(null)
  useFrame((state) => {
    if (!group.current) return
    const t = state.clock.elapsedTime
    group.current.rotation.y = Math.sin(t * 0.12) * 0.15
    group.current.position.y = Math.sin(t * 0.55) * 0.08
  })
  return <group ref={group}>{children}</group>
}

function UniverseFX() {
  return (
    <EffectComposer multisampling={0}>
      <Bloom
        intensity={1.35}
        luminanceThreshold={0.18}
        luminanceSmoothing={0.35}
        mipmapBlur
      />
      <Noise opacity={0.035} />
      <Vignette eskil={false} offset={0.18} darkness={0.85} />
    </EffectComposer>
  )
}

export function Scene3D({
  radar,
  signalCount = 0,
  allowZoom = false,
}: {
  radar: RadarSnapshot | null
  signalCount?: number
  allowZoom?: boolean
}) {
  const green = radar?.green ?? 0
  const grey = radar?.grey ?? 0
  const red = radar?.red ?? 0
  const [ready, setReady] = useState(false)
  const orbitCount = Math.max(10, Math.min(16, green + red + 8 + Math.min(4, signalCount)))

  return (
    <div className="relative h-full min-h-[420px] w-full overflow-hidden rounded-[28px] neon-border glass scanlines universe-frame">
      {!ready && (
        <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center universe-boot">
          <div className="text-center">
            <p className="hud-kicker">Booting Orbis…</p>
            <p className="hud-meta">WebGL · bloom · orbit tokens</p>
          </div>
        </div>
      )}
      <Canvas
        camera={{ position: [0, 2.1, 8.2], fov: 40, near: 0.1, far: 200 }}
        dpr={[1, 1.75]}
        gl={{ antialias: true, powerPreference: 'high-performance', alpha: false }}
        onCreated={({ gl }) => {
          gl.setClearColor(VOID, 1)
          gl.toneMapping = THREE.ACESFilmicToneMapping
          gl.toneMappingExposure = 1.15
          setReady(true)
        }}
      >
        <color attach="background" args={[VOID]} />
        <fog attach="fog" args={[VOID, 10, 28]} />
        <ambientLight intensity={0.28} />
        <pointLight position={[5, 6, 3]} intensity={55} color={CYAN} distance={30} />
        <pointLight position={[-6, -1, -4]} intensity={42} color={MAGENTA} distance={28} />
        <pointLight position={[0, 4, -2]} intensity={28} color={AMBER} distance={20} />
        <spotLight
          position={[0, 8, 4]}
          angle={0.45}
          penumbra={0.6}
          intensity={1.4}
          color="#e8f0ff"
        />

        <Stars radius={80} depth={50} count={2800} factor={3.2} saturation={0.7} fade speed={0.55} />
        <Sparkles count={80} scale={12} size={2.5} speed={0.35} opacity={0.55} color={CYAN} />
        <Sparkles count={50} scale={10} size={3} speed={0.25} opacity={0.4} color={MAGENTA} />

        <Rig>
          <HoloCore green={green} grey={grey} red={red} />
          <WireShell />
          <NeonRings />
          <EnergyBeams />
          <TokenOrbit count={orbitCount} radius={2.7} speed={0.28} y={0.15} tilt={0.22} />
          <TokenOrbit count={Math.max(8, orbitCount - 4)} radius={3.55} speed={-0.16} y={-0.35} tilt={-0.35} />
          <SymbolNebula radar={radar} />
        </Rig>
        <DataFloor />

        <OrbitControls
          enablePan={false}
          enableZoom={allowZoom}
          minDistance={5.5}
          maxDistance={14}
          minPolarAngle={Math.PI / 3.2}
          maxPolarAngle={Math.PI / 1.85}
          autoRotate
          autoRotateSpeed={0.35}
          dampingFactor={0.08}
          enableDamping
        />
        <UniverseFX />
      </Canvas>

      <div className="pointer-events-none absolute inset-x-0 top-0 flex justify-between p-4">
        <div className="hud" style={{ background: 'rgba(8,12,18,0.88)', border: '1px solid rgba(126,224,234,0.32)' }}>
          <p className="hud-kicker">Orbis Universe</p>
          <p className="hud-meta">RGG nebula · orbit tokens</p>
        </div>
        <div className="hud" style={{ background: 'rgba(8,12,18,0.88)', border: '1px solid rgba(126,224,234,0.32)' }}>
          <p className="hud-meta">Bloom · ACES · fog</p>
        </div>
      </div>

      <div className="pointer-events-none absolute inset-x-0 bottom-0 p-4">
        <div className="flex items-end justify-between gap-3">
          <div className="hud" style={{ background: 'rgba(8,12,18,0.88)', border: '1px solid rgba(126,224,234,0.32)' }}>
            <p className="hud-kicker">Live radar core</p>
            <p className="hud-meta">
              {radar?.as_of
                ? `1D closed through ${radar.as_of.slice(0, 10)}`
                : 'Awaiting daily snapshot · decorative nebula'}
            </p>
          </div>
          <div className="hud flex gap-4 font-mono text-sm tabular" style={{ background: 'rgba(8,12,18,0.88)', border: '1px solid rgba(126,224,234,0.32)' }}>
            <span className="text-lime">G {green}</span>
            <span className="text-[#c5d0dc]">Gy {grey}</span>
            <span className="text-magenta">R {red}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

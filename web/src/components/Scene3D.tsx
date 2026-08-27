import { Canvas, useFrame, useLoader } from '@react-three/fiber'
import {
  Billboard,
  ContactShadows,
  Environment,
  Lightformer,
  MeshTransmissionMaterial,
  OrbitControls,
  Sparkles,
  Stars,
} from '@react-three/drei'
import { Bloom, EffectComposer, Noise, Vignette } from '@react-three/postprocessing'
import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import * as THREE from 'three'
import type { RadarSnapshot } from '../types'
import { LOGO_HALO, orbitLogoIds, type CryptoLogoId } from '../cryptoLogos'

const CYAN = '#5ee9f2'
const MAGENTA = '#ff4d9a'
const AMBER = '#ffc45c'
const VOID = '#02040a'
const VOID_COLOR = new THREE.Color(VOID)

function mixRadarColor(green: number, grey: number, red: number) {
  const total = Math.max(1, green + grey + red)
  const g = green / total
  const r = red / total
  const gy = grey / total
  return new THREE.Color().setRGB(
    0.18 + r * 0.72 + gy * 0.22,
    0.42 + g * 0.48 + gy * 0.12,
    0.78 - r * 0.4 + g * 0.12,
  )
}

function usePrefersReducedMotion() {
  const [reduce, setReduce] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setReduce(mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])
  return reduce
}

function GlassCore({
  green,
  grey,
  red,
  reduce,
}: {
  green: number
  grey: number
  red: number
  reduce: boolean
}) {
  const spin = useRef<THREE.Group>(null)
  const inner = useRef<THREE.Mesh>(null)
  const color = useMemo(() => mixRadarColor(green, grey, red), [green, grey, red])
  const hex = `#${color.getHexString()}`

  useFrame((state, dt) => {
    if (reduce) return
    if (spin.current) spin.current.rotation.y += dt * 0.18
    if (inner.current) {
      inner.current.rotation.y -= dt * 0.42
      inner.current.rotation.z += dt * 0.16
      const pulse = 1 + Math.sin(state.clock.elapsedTime * 1.4) * 0.06
      inner.current.scale.setScalar(pulse)
    }
  })

  return (
    <group ref={spin}>
      <pointLight color={hex} intensity={18} distance={8} decay={2} />
      <mesh ref={inner}>
        <sphereGeometry args={[0.36, 32, 32]} />
        <meshStandardMaterial
          color={hex}
          emissive={hex}
          emissiveIntensity={3.2}
          metalness={0.05}
          roughness={0.18}
        />
      </mesh>
      <mesh scale={0.62}>
        <icosahedronGeometry args={[1, 0]} />
        <meshBasicMaterial color={hex} wireframe transparent opacity={0.35} />
      </mesh>
      <mesh>
        <sphereGeometry args={[1.08, 64, 64]} />
        <MeshTransmissionMaterial
          backside
          samples={6}
          resolution={256}
          transmission={1}
          roughness={0.08}
          thickness={0.55}
          ior={1.42}
          chromaticAberration={0.28}
          anisotropy={0.35}
          distortion={reduce ? 0 : 0.18}
          distortionScale={0.22}
          temporalDistortion={reduce ? 0 : 0.08}
          color="#c8f7ff"
          attenuationColor={hex}
          attenuationDistance={2.4}
          background={VOID_COLOR}
        />
      </mesh>
      <mesh scale={1.22}>
        <sphereGeometry args={[1, 48, 48]} />
        <meshBasicMaterial
          color={hex}
          transparent
          opacity={0.09}
          side={THREE.BackSide}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>
    </group>
  )
}

function OrbitRail({
  rx,
  rz,
  color,
  tilt,
  y,
}: {
  rx: number
  rz: number
  color: string
  tilt: number
  y: number
}) {
  const geom = useMemo(() => {
    const curve = new THREE.EllipseCurve(0, 0, rx, rz, 0, Math.PI * 2, false, 0)
    const pts = curve.getPoints(160).map((p) => new THREE.Vector3(p.x, 0, p.y))
    const path = new THREE.CatmullRomCurve3(pts, true)
    return new THREE.TubeGeometry(path, 160, 0.011, 8, true)
  }, [rx, rz])

  useEffect(() => () => geom.dispose(), [geom])

  return (
    <mesh geometry={geom} position={[0, y, 0]} rotation={[tilt, 0.12, 0]}>
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.7}
        metalness={1}
        roughness={0.22}
        transparent
        opacity={0.85}
      />
    </mesh>
  )
}

function LogoCoin({ id }: { id: CryptoLogoId }) {
  const tex = useLoader(THREE.TextureLoader, `/crypto/${id}.png`)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
  tex.needsUpdate = true
  const halo = LOGO_HALO[id] ?? CYAN

  return (
    <Billboard follow>
      <mesh>
        <circleGeometry args={[0.38, 64]} />
        <meshBasicMaterial color="#080c12" />
      </mesh>
      <mesh position={[0, 0, 0.004]}>
        <circleGeometry args={[0.34, 64]} />
        <meshBasicMaterial map={tex} toneMapped={false} transparent />
      </mesh>
      <mesh position={[0, 0, -0.012]} scale={1.08}>
        <ringGeometry args={[0.335, 0.4, 64]} />
        <meshBasicMaterial
          color={halo}
          transparent
          opacity={0.75}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          side={THREE.DoubleSide}
        />
      </mesh>
    </Billboard>
  )
}

function TokenOrbit({
  logos,
  rx,
  rz,
  speed,
  y,
  tilt,
  reduce,
}: {
  logos: CryptoLogoId[]
  rx: number
  rz: number
  speed: number
  y: number
  tilt: number
  reduce: boolean
}) {
  const holders = useRef<(THREE.Group | null)[]>([])
  const n = logos.length
  const tokens = useMemo(
    () =>
      logos.map((id, i) => ({
        id,
        phase: n ? (i / n) * Math.PI * 2 : 0,
        scale: 0.92 + (i % 4) * 0.08,
      })),
    [logos, n],
  )

  useFrame((state) => {
    const t = state.clock.elapsedTime
    const s = reduce ? 0 : speed
    for (let i = 0; i < tokens.length; i++) {
      const g = holders.current[i]
      if (!g) continue
      const a = t * s + tokens[i].phase
      g.position.set(Math.cos(a) * rx, Math.sin(a * 2) * 0.07, Math.sin(a) * rz)
    }
  })

  return (
    <group position={[0, y, 0]} rotation={[tilt, 0.12, 0]}>
      {tokens.map((tok, i) => (
        <group
          key={`${tok.id}-${i}`}
          ref={(el) => {
            holders.current[i] = el
          }}
          position={[Math.cos(tok.phase) * rx, 0, Math.sin(tok.phase) * rz]}
          scale={tok.scale}
        >
          <Suspense fallback={null}>
            <LogoCoin id={tok.id} />
          </Suspense>
        </group>
      ))}
    </group>
  )
}

function SymbolNebula({ radar, reduce }: { radar: RadarSnapshot | null; reduce: boolean }) {
  const points = useRef<THREE.Points>(null)
  const { positions, colors, sizes } = useMemo(() => {
    const rows = radar?.rows?.slice(0, 220) ?? []
    const n = Math.max(rows.length, 160)
    const pos = new Float32Array(n * 3)
    const col = new Float32Array(n * 3)
    const sz = new Float32Array(n)
    for (let i = 0; i < n; i++) {
      const row = rows[i]
      const shell = 3.35 + (i % 11) * 0.18 + (i % 5) * 0.04
      const a = (i / n) * Math.PI * 2 + (i % 7) * 0.09
      const y = Math.sin(i * 0.31) * 1.15 + ((i % 13) - 6) * 0.06
      pos[i * 3] = Math.cos(a) * shell
      pos[i * 3 + 1] = y
      pos[i * 3 + 2] = Math.sin(a) * shell
      const c =
        row?.color === 'GREEN'
          ? [0.35, 1, 0.55]
          : row?.color === 'RED'
            ? [1, 0.28, 0.55]
            : row?.color === 'GREY'
              ? [0.62, 0.7, 0.88]
              : [0.4 + (i % 5) * 0.07, 0.7 + (i % 3) * 0.08, 0.92]
      col[i * 3] = c[0]
      col[i * 3 + 1] = c[1]
      col[i * 3 + 2] = c[2]
      sz[i] = 0.05 + (i % 5) * 0.018
    }
    return { positions: pos, colors: col, sizes: sz }
  }, [radar])

  useFrame((_, dt) => {
    if (!points.current || reduce) return
    points.current.rotation.y += dt * 0.045
    points.current.rotation.x = Math.sin(performance.now() * 0.00012) * 0.06
  })

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
        <bufferAttribute attach="attributes-size" args={[sizes, 1]} />
      </bufferGeometry>
      <pointsMaterial
        size={0.08}
        vertexColors
        transparent
        opacity={0.88}
        sizeAttenuation
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  )
}

function ObsidianFloor() {
  return (
    <group position={[0, -2.28, 0]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[5.4, 80]} />
        <meshPhysicalMaterial
          color="#070b12"
          metalness={0.92}
          roughness={0.18}
          clearcoat={0.55}
          envMapIntensity={0.7}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.012, 0]}>
        <ringGeometry args={[2.05, 2.12, 96]} />
        <meshBasicMaterial color={CYAN} transparent opacity={0.35} side={THREE.DoubleSide} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.014, 0]}>
        <ringGeometry args={[3.15, 3.22, 96]} />
        <meshBasicMaterial color={MAGENTA} transparent opacity={0.22} side={THREE.DoubleSide} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.016, 0]}>
        <ringGeometry args={[4.35, 4.42, 96]} />
        <meshBasicMaterial color={AMBER} transparent opacity={0.16} side={THREE.DoubleSide} />
      </mesh>
    </group>
  )
}

function Rig({ children, reduce }: { children: ReactNode; reduce: boolean }) {
  const group = useRef<THREE.Group>(null)
  useFrame((state) => {
    if (!group.current || reduce) return
    const t = state.clock.elapsedTime
    group.current.rotation.y = Math.sin(t * 0.1) * 0.12
    group.current.position.y = Math.sin(t * 0.42) * 0.06
  })
  return <group ref={group}>{children}</group>
}

function StudioLights() {
  return (
    <Environment frames={1} resolution={256} environmentIntensity={0.7}>
      <Lightformer form="rect" intensity={3.2} color="#9af4ff" position={[5, 3.5, 2]} scale={[8, 1.2, 1]} />
      <Lightformer form="rect" intensity={1.8} color="#ff7ec8" position={[-5, 1.2, -3]} scale={[5, 2.2, 1]} />
      <Lightformer form="ring" intensity={1.5} color="#ffe08a" position={[0, 5.5, -1]} scale={5} />
      <Lightformer form="rect" intensity={0.9} color="#e8f4ff" position={[0, -3, 4]} scale={[10, 3, 1]} />
    </Environment>
  )
}

function UniverseFX() {
  return (
    <EffectComposer multisampling={0}>
      <Bloom intensity={0.95} luminanceThreshold={0.22} luminanceSmoothing={0.4} mipmapBlur />
      <Noise opacity={0.018} />
      <Vignette eskil={false} offset={0.22} darkness={0.72} />
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
  const reduce = usePrefersReducedMotion()
  const innerCount = Math.max(10, Math.min(14, green + red + 8 + Math.min(3, signalCount)))
  const outerCount = Math.max(8, innerCount - 3)
  const logos = useMemo(() => {
    const symbols = radar?.rows?.map((r) => r.symbol) ?? []
    return orbitLogoIds(symbols, innerCount + outerCount)
  }, [radar, innerCount, outerCount])
  const innerLogos = logos.slice(0, innerCount)
  const outerLogos = logos.slice(innerCount, innerCount + outerCount)

  return (
    <div className="relative h-full min-h-[420px] w-full overflow-hidden rounded-[28px] neon-border glass scanlines universe-frame">
      {!ready && (
        <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center universe-boot">
          <div className="text-center">
            <p className="hud-kicker">Booting Orbis…</p>
            <p className="hud-meta">Glass core · crypto logos</p>
          </div>
        </div>
      )}
      <Canvas
        camera={{ position: [0, 1.85, 7.6], fov: 38, near: 0.1, far: 200 }}
        dpr={[1, 1.6]}
        gl={{ antialias: true, powerPreference: 'high-performance', alpha: false }}
        onCreated={({ gl }) => {
          gl.setClearColor(VOID, 1)
          gl.toneMapping = THREE.ACESFilmicToneMapping
          gl.toneMappingExposure = 1.05
          setReady(true)
        }}
      >
        <color attach="background" args={[VOID]} />
        <fog attach="fog" args={[VOID, 9, 26]} />
        <ambientLight intensity={0.18} />
        <pointLight position={[4, 5, 3]} intensity={28} color={CYAN} distance={22} />
        <pointLight position={[-5, 1, -3]} intensity={18} color={MAGENTA} distance={20} />
        <spotLight position={[0, 7, 4]} angle={0.42} penumbra={0.7} intensity={1.1} color="#f4fbff" />
        <StudioLights />

        <Stars radius={70} depth={42} count={2200} factor={2.6} saturation={0.45} fade speed={reduce ? 0 : 0.28} />
        <Sparkles count={48} scale={11} size={2.2} speed={reduce ? 0 : 0.22} opacity={0.42} color={CYAN} />
        <Sparkles count={28} scale={9} size={2.8} speed={reduce ? 0 : 0.16} opacity={0.28} color={MAGENTA} />

        <Rig reduce={reduce}>
          <GlassCore green={green} grey={grey} red={red} reduce={reduce} />
          <OrbitRail rx={2.55} rz={2.15} color={CYAN} tilt={0.28} y={0.12} />
          <OrbitRail rx={3.35} rz={2.75} color={MAGENTA} tilt={-0.32} y={-0.28} />
          <OrbitRail rx={4.05} rz={3.35} color={AMBER} tilt={0.08} y={0.02} />
          <TokenOrbit logos={innerLogos} rx={2.55} rz={2.15} speed={0.32} y={0.12} tilt={0.28} reduce={reduce} />
          <TokenOrbit logos={outerLogos} rx={3.35} rz={2.75} speed={-0.18} y={-0.28} tilt={-0.32} reduce={reduce} />
          <SymbolNebula radar={radar} reduce={reduce} />
        </Rig>
        <ObsidianFloor />
        <ContactShadows position={[0, -2.26, 0]} opacity={0.55} scale={14} blur={2.4} far={6} color="#000000" />

        <OrbitControls
          enablePan={false}
          enableZoom={allowZoom}
          minDistance={5.2}
          maxDistance={13}
          minPolarAngle={Math.PI / 3.4}
          maxPolarAngle={Math.PI / 1.82}
          autoRotate={!reduce}
          autoRotateSpeed={0.28}
          dampingFactor={0.08}
          enableDamping
        />
        <UniverseFX />
      </Canvas>

      <div className="pointer-events-none absolute inset-x-0 top-0 flex justify-between p-4">
        <div className="hud" style={{ background: 'rgba(8,12,18,0.88)', border: '1px solid rgba(126,224,234,0.32)' }}>
          <p className="hud-kicker">Orbis Universe</p>
          <p className="hud-meta">Famous logos on the rails</p>
        </div>
        <div className="hud" style={{ background: 'rgba(8,12,18,0.88)', border: '1px solid rgba(126,224,234,0.32)' }}>
          <p className="hud-meta">Transmission · ACES · fog</p>
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
          <div
            className="hud flex gap-4 font-mono text-sm tabular"
            style={{ background: 'rgba(8,12,18,0.88)', border: '1px solid rgba(126,224,234,0.32)' }}
          >
            <span className="text-lime">G {green}</span>
            <span className="text-[#c5d0dc]">Gy {grey}</span>
            <span className="text-magenta">R {red}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

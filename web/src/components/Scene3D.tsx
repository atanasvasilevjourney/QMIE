import { Canvas, useFrame } from '@react-three/fiber'
import { Float, MeshDistortMaterial, Stars } from '@react-three/drei'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { RadarSnapshot } from '../types'

function HoloCore({ green, grey, red }: { green: number; grey: number; red: number }) {
  const mesh = useRef<THREE.Mesh>(null)
  const total = Math.max(1, green + grey + red)
  const g = green / total
  const r = red / total
  useFrame((_, dt) => {
    if (!mesh.current) return
    mesh.current.rotation.y += dt * 0.35
    mesh.current.rotation.x += dt * 0.12
  })
  const color = new THREE.Color().setRGB(0.15 + r * 0.85, 0.7 * g + 0.2, 1 - r * 0.4)
  return (
    <mesh ref={mesh} scale={1.35}>
      <icosahedronGeometry args={[1, 2]} />
      <MeshDistortMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.55}
        roughness={0.15}
        metalness={0.85}
        distort={0.28}
        speed={2.2}
        wireframe={false}
        transparent
        opacity={0.92}
      />
    </mesh>
  )
}

function WireShell() {
  const ref = useRef<THREE.Mesh>(null)
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.y -= dt * 0.18
  })
  return (
    <mesh ref={ref} scale={1.7}>
      <icosahedronGeometry args={[1, 1]} />
      <meshBasicMaterial color="#00f0ff" wireframe transparent opacity={0.35} />
    </mesh>
  )
}

function NeonTorii() {
  const a = useRef<THREE.Mesh>(null)
  const b = useRef<THREE.Mesh>(null)
  useFrame((_, dt) => {
    if (a.current) a.current.rotation.x += dt * 0.4
    if (b.current) b.current.rotation.z -= dt * 0.32
  })
  return (
    <group>
      <mesh ref={a} rotation={[Math.PI / 2.4, 0.2, 0]}>
        <torusGeometry args={[2.15, 0.02, 12, 96]} />
        <meshBasicMaterial color="#ff2bd6" transparent opacity={0.75} />
      </mesh>
      <mesh ref={b} rotation={[0.4, 0.6, Math.PI / 5]}>
        <torusGeometry args={[2.45, 0.015, 12, 96]} />
        <meshBasicMaterial color="#00f0ff" transparent opacity={0.55} />
      </mesh>
    </group>
  )
}

function TokenRing({ count, color }: { count: number; color: string }) {
  const group = useRef<THREE.Group>(null)
  const tokens = useMemo(() => {
    const n = Math.min(24, Math.max(6, count || 8))
    return Array.from({ length: n }, (_, i) => {
      const a = (i / n) * Math.PI * 2
      return { x: Math.cos(a) * 2.6, z: Math.sin(a) * 2.6, y: Math.sin(a * 2) * 0.25 }
    })
  }, [count])
  useFrame((_, dt) => {
    if (group.current) group.current.rotation.y += dt * 0.25
  })
  return (
    <group ref={group}>
      {tokens.map((t, i) => (
        <Float key={i} speed={1.5 + (i % 5) * 0.2} floatIntensity={0.6} rotationIntensity={0.4}>
          <mesh position={[t.x, t.y, t.z]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.18, 0.18, 0.05, 24]} />
            <meshStandardMaterial
              color={color}
              emissive={color}
              emissiveIntensity={0.7}
              metalness={1}
              roughness={0.2}
            />
          </mesh>
        </Float>
      ))}
    </group>
  )
}

function ParticleField({ radar }: { radar: RadarSnapshot | null }) {
  const points = useRef<THREE.Points>(null)
  const { positions, colors } = useMemo(() => {
    const rows = radar?.rows?.slice(0, 180) ?? []
    const n = Math.max(rows.length, 60)
    const pos = new Float32Array(n * 3)
    const col = new Float32Array(n * 3)
    for (let i = 0; i < n; i++) {
      const row = rows[i]
      const radius = 3.2 + (i % 7) * 0.18
      const a = (i / n) * Math.PI * 2
      const y = ((i % 11) - 5) * 0.22
      pos[i * 3] = Math.cos(a) * radius
      pos[i * 3 + 1] = y
      pos[i * 3 + 2] = Math.sin(a) * radius
      const c =
        row?.color === 'GREEN'
          ? [0.1, 1, 0.45]
          : row?.color === 'RED'
            ? [1, 0.2, 0.45]
            : [0.55, 0.65, 0.85]
      col[i * 3] = c[0]
      col[i * 3 + 1] = c[1]
      col[i * 3 + 2] = c[2]
    }
    return { positions: pos, colors: col }
  }, [radar])

  useFrame((_, dt) => {
    if (points.current) points.current.rotation.y += dt * 0.08
  })

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
      </bufferGeometry>
      <pointsMaterial size={0.08} vertexColors transparent opacity={0.9} sizeAttenuation />
    </points>
  )
}

export function Scene3D({ radar }: { radar: RadarSnapshot | null }) {
  // Use real counts only — never invent a live mix while loading/failed.
  const green = radar?.green ?? 0
  const grey = radar?.grey ?? 0
  const red = radar?.red ?? 0
  return (
    <div className="relative h-full min-h-[320px] w-full overflow-hidden rounded-[28px] neon-border glass scanlines">
      <Canvas camera={{ position: [0, 1.4, 7.2], fov: 42 }} dpr={[1, 1.75]}>
        <color attach="background" args={['#05060a']} />
        <ambientLight intensity={0.35} />
        <pointLight position={[4, 5, 2]} intensity={40} color="#00f0ff" />
        <pointLight position={[-4, -2, -3]} intensity={28} color="#ff2bd6" />
        <Stars radius={60} depth={40} count={1800} factor={3} saturation={0.6} fade speed={0.6} />
        <HoloCore green={green} grey={grey} red={red} />
        <WireShell />
        <NeonTorii />
        <TokenRing count={green + red + 6} color="#ffb020" />
        <ParticleField radar={radar} />
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -2.2, 0]}>
          <circleGeometry args={[5.5, 64]} />
          <meshBasicMaterial color="#00f0ff" transparent opacity={0.05} />
        </mesh>
      </Canvas>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 p-4">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="font-display text-[11px] tracking-[0.35em] text-cyan uppercase">
              Live Radar Core
            </p>
            <p className="mt-1 font-mono text-xs text-chrome/80">
              {radar?.as_of
                ? `1D closed through ${radar.as_of.slice(0, 10)}`
                : 'awaiting daily snapshot'}
            </p>
          </div>
          <div className="flex gap-3 font-mono text-[11px]">
            <span className="text-lime">G {green}</span>
            <span className="text-chrome/70">Gy {grey}</span>
            <span className="text-magenta">R {red}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

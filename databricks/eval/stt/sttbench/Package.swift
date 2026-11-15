// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "sttbench",
    platforms: [.macOS(.v15)],
    dependencies: [.package(url: "https://github.com/FluidInference/FluidAudio.git", exact: "0.18.3")],
    targets: [
        .executableTarget(
            name: "sttbench",
            dependencies: [.product(name: "FluidAudio", package: "FluidAudio")],
            swiftSettings: [.swiftLanguageMode(.v5)])
    ]
)

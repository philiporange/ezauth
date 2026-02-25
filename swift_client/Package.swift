// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "EZAuth",
    platforms: [
        .iOS(.v15),
        .macOS(.v12),
        .tvOS(.v15),
        .watchOS(.v8),
    ],
    products: [
        .library(name: "EZAuth", targets: ["EZAuth"]),
    ],
    targets: [
        .target(name: "EZAuth"),
    ]
)

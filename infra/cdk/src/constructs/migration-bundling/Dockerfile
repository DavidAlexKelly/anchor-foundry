# Thin wrapper around the official Lambda Python 3.12 bundling image, built
# for a pinned platform (see migration.ts's MigrationTriggerConstruct).
#
# aws-cdk-lib 2.150.0's asset bundling silently drops the `bundling.platform`
# runtime option for both BIND_MOUNT and VOLUME_COPY file access (neither
# AssetBundlingBindMount nor AssetBundlingVolumeCopy forward it to the
# eventual `docker run`) - confirmed by reading aws-cdk-lib's own source,
# not assumed. `DockerImage.fromBuild`'s `platform` option, in contrast, IS
# correctly passed to `docker build --platform`, producing a single-arch
# image that needs no further --platform flag at run time. Building this
# thin FROM-only layer is the only reliable way in this CDK version to pin
# the bundling container's architecture regardless of the host machine
# running `cdk deploy` - without it, `docker run` defaults to the host's
# native architecture (e.g. arm64 on Apple Silicon), producing a
# psycopg_binary wheel that mismatches the Lambda function's own
# architecture and fails at runtime with "no pq wrapper available".
#
# **Pinned by digest (§818)**, as STATUS.md §20 asked: the bundling image's
# resolved digest feeds the bundled asset's hash, so an upstream update to a
# mutable tag churned the migration Lambda's logical id between two deploys of
# the same commit and collided with `AlreadyExists`. Bump with
# scripts/pin-images.sh.
FROM public.ecr.aws/sam/build-python3.12:latest@sha256:869de679919e2f11cdd8241448a1f8e67a76265b431b7e4edad4566fed7619d0

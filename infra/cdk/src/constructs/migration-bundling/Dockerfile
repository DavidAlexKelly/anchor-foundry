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
# Pinned to a specific digest, not `:latest` - confirmed live that an
# unpinned tag can resolve a different upstream image on a later rebuild
# with zero change to packages/db's actual source, which churns this
# Lambda's config hash and therefore its `currentVersion` logical ID.
# CloudFormation then tries to publish a "new" version whose $LATEST is
# byte-identical to one already published under the old logical ID,
# and AWS Lambda's PublishVersion just hands back that existing version
# number instead of minting a new one - a collision CloudFormation
# reports as `AlreadyExists`, blocking the whole deploy. Pinning the
# digest keeps the hash - and this resource's identity - stable across
# deploys when nothing has actually changed.
FROM public.ecr.aws/sam/build-python3.12@sha256:b24c57c83fb3270dcf82b1ec9860416a978e1e605cf87c51b27fc0e5c1bbab74

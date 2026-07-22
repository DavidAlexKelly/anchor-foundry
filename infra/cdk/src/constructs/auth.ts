import { Duration, RemovalPolicy } from "aws-cdk-lib";
import * as cognito from "aws-cdk-lib/aws-cognito";
import { Construct } from "constructs";

export interface AuthConstructProps {
  /** Customer org slug, used for the hosted UI domain prefix. */
  readonly orgSlug: string;
  /** Platform URL, e.g. https://acme.platform.example — OAuth callback target. */
  readonly platformUrl: string;
}

/**
 * One Cognito User Pool per customer organisation (spec §9), provisioned
 * automatically during deployment. Every setting below is a verbatim
 * security default from spec §9 "Cognito Setup in CDK" — do not relax any
 * of them without a documented review.
 */
export class AuthConstruct extends Construct {
  public readonly userPool: cognito.UserPool;
  public readonly userPoolClient: cognito.UserPoolClient;
  public readonly userPoolDomain: cognito.UserPoolDomain;

  constructor(scope: Construct, id: string, props: AuthConstructProps) {
    super(scope, id);

    this.userPool = new cognito.UserPool(this, "UserPool", {
      // §9: invitation only, no public registration.
      selfSignUpEnabled: false,
      // §9: email login only.
      signInAliases: { email: true },
      signInCaseSensitive: false,
      autoVerify: { email: true },
      // §9: MFA optional (admins encouraged to require), TOTP only — no SMS.
      mfa: cognito.Mfa.OPTIONAL,
      mfaSecondFactor: { otp: true, sms: false },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
        tempPasswordValidity: Duration.days(7),
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      // Deleting the stack must not silently destroy the customer's user
      // directory; destroy is an explicit control-plane operation.
      removalPolicy: RemovalPolicy.RETAIN,
    });

    this.userPoolClient = this.userPool.addClient("WebClient", {
      // §9: SRP only — the password is never transmitted in plain text.
      authFlows: { userSrp: true, userPassword: false, adminUserPassword: false, custom: false },
      // §9: don't reveal whether an email is registered.
      preventUserExistenceErrors: true,
      // §9: short-lived access tokens, 30-day refresh.
      accessTokenValidity: Duration.minutes(15),
      idTokenValidity: Duration.minutes(15),
      refreshTokenValidity: Duration.days(30),
      generateSecret: false, // public client: browser PKCE flow
      oAuth: {
        flows: { authorizationCodeGrant: true, implicitCodeGrant: false },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
        callbackUrls: [`${props.platformUrl}/callback`],
        logoutUrls: [`${props.platformUrl}/login`],
      },
    });

    this.userPoolDomain = this.userPool.addDomain("HostedUi", {
      cognitoDomain: { domainPrefix: `platform-${props.orgSlug}` },
    });
  }
}

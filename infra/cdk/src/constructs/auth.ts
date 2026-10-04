import { Duration, RemovalPolicy } from "aws-cdk-lib";
import * as cognito from "aws-cdk-lib/aws-cognito";
import { Construct } from "constructs";

export interface AuthConstructProps {
  /** Customer org slug, used for the hosted UI domain prefix. */
  readonly orgSlug: string;
}

/**
 * One Cognito User Pool per customer organisation (spec §9), provisioned
 * automatically during deployment. Every setting below is a verbatim
 * security default from spec §9 "Cognito Setup in CDK" - do not relax any
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
      // §9: MFA optional (admins encouraged to require), TOTP only - no SMS.
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
      // §9: SRP only - the password is never transmitted in plain text.
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
        // Replaced by `allowAddresses`, which the stack calls once it knows
        // where the platform is served. Required here only because the
        // construct refuses a code grant with no callback at all.
        callbackUrls: [UNSET_ADDRESS],
        logoutUrls: [UNSET_ADDRESS],
      },
    });
    this.node.addValidation({
      validate: () => (this.addressesAllowed ? [] : [
        "AuthConstruct.allowAddresses was never called: the hosted UI would send nobody back",
      ]),
    });

    this.userPoolDomain = this.userPool.addDomain("HostedUi", {
      cognitoDomain: { domainPrefix: `platform-${props.orgSlug}` },
    });
  }

  private addressesAllowed = false;

  /**
   * The addresses the platform is served at, each as `https://host`: the
   * hosted UI sends a viewer back to `<address>/callback` after sign-in and
   * to `<address>/login` after sign-out, and only to an address on this list.
   *
   * **The web app asks for its own origin** (`apps/web/src/lib/auth.ts`:
   * `window.location.origin + "/callback"`), so the list has to hold the
   * address viewers actually reach. It held only the `platformUrl` context
   * until §849 - which the control plane filled with a placeholder,
   * `https://<slug>.platform.example.com`, on a first deploy, and with the
   * distribution's bare domain, no scheme, on every deploy after. Neither is
   * an address the distribution answers on, so the hosted UI refused every
   * sign-in on a deployed stack.
   */
  public allowAddresses(addresses: string[]): void {
    const client = this.userPoolClient.node.defaultChild as cognito.CfnUserPoolClient;
    client.callbackUrLs = addresses.map((a) => `${a}/callback`);
    client.logoutUrLs = addresses.map((a) => `${a}/login`);
    this.addressesAllowed = true;
  }
}

const UNSET_ADDRESS = "https://unset.invalid/";

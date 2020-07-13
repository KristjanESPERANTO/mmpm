import { Injectable } from "@angular/core";
import { BehaviorSubject, Observable } from "rxjs";
import { MagicMirrorPackage } from "src/app/interfaces/interfaces";
import { RestApiService } from "src/app/services/rest-api.service";
import { URLS } from "src/app/utils/urls";

@Injectable({
  providedIn: "root"
})
export class DataStoreService {
  constructor(private api: RestApiService) {}

  private _marketplacePackages: BehaviorSubject<MagicMirrorPackage[]> = new BehaviorSubject<Array<MagicMirrorPackage>>([]);
  private _installedPackages: BehaviorSubject<MagicMirrorPackage[]> = new BehaviorSubject<Array<MagicMirrorPackage>>([]);
  private _externalPackages: BehaviorSubject<MagicMirrorPackage[]> = new BehaviorSubject<Array<MagicMirrorPackage>>([]);
  private _availableUpgrades: BehaviorSubject<Object> = new BehaviorSubject<Object>({});
  private _mmpmEnvironmentVariables: BehaviorSubject<Map<string, string>> = new BehaviorSubject<Map<string, string>>(new Map<string, string>());
  private _upgradablePackages: BehaviorSubject<Array<MagicMirrorPackage>> = new BehaviorSubject<Array<MagicMirrorPackage>>([]);

  public readonly marketplacePackages: Observable<MagicMirrorPackage[]> = this._marketplacePackages.asObservable();
  public readonly installedPackages: Observable<MagicMirrorPackage[]> = this._installedPackages.asObservable();
  public readonly externalPackages: Observable<MagicMirrorPackage[]> = this._externalPackages.asObservable();
  public readonly availableUpgrades: Observable<Object> = this._availableUpgrades.asObservable();
  public readonly mmpmEnvironmentVariables: Observable<Map<string, string>> = this._mmpmEnvironmentVariables.asObservable();
  public readonly upgradeablePackages: Observable<Array<MagicMirrorPackage>> = this._upgradablePackages.asObservable();

  public ngOnInit() {}

  private fill(data: any): Array<MagicMirrorPackage> {
    let array = new Array<MagicMirrorPackage>();

    Object.keys(data).forEach((_category) => {
      if (data) {
        for (const pkg of data[_category]) {
          array.push({
            category: _category,
            title: pkg["title"],
            description: pkg["description"],
            author: pkg["author"],
            repository: pkg["repository"],
            directory: pkg["directory"]
          });
        }
      }
    });

    return array;
  }

  private isSamePackage(a: MagicMirrorPackage, b: MagicMirrorPackage): boolean {
    return a.title === b.title && a.repository === b.repository && a.author === b.author && a.category === b.category;
  }

  public loadData(): void {
    this.api.retrieve(URLS.GET.MMPM.ENVIRONMENT_VARS).then((envVars: any) => {
      let tempMap = new Map<string, string>();
      Object.keys(envVars).forEach((key) => tempMap.set(key, envVars[key]));
      this._mmpmEnvironmentVariables.next(tempMap);
    }).catch((error) => console.log(error));

    this.api.retrieve(URLS.GET.PACKAGES.UPDATE).then((_) => {
      this.api.retrieve(URLS.GET.PACKAGES.UPGRADEABLE).then((upgradeable) => {
        this._upgradablePackages.next(upgradeable["packages"]);
      }).catch((error) => console.log(error));
    }).catch((error) => console.log(error));

    this.api.retrieve(URLS.GET.PACKAGES.MARKETPLACE).then((allPkgs: Array<MagicMirrorPackage>) => {
      this.api.retrieve(URLS.GET.PACKAGES.INSTALLED).then((installedPkgs: Array<MagicMirrorPackage>) => {
        this.api.retrieve(URLS.GET.PACKAGES.EXTERNAL).then((extPkgs: Array<MagicMirrorPackage>) => {

          extPkgs = this.fill(extPkgs);
          installedPkgs = this.fill(installedPkgs);

          allPkgs = [...this.fill(allPkgs), ...extPkgs];

          // removing all the packages that are currently installed from the list of available packages
          for (const installedPkg of installedPkgs) {
            let index: number = allPkgs.findIndex((available: MagicMirrorPackage) => {
              return this.isSamePackage(available, installedPkg)
            });

            if (index > -1) {
              allPkgs.splice(index, 1);
            }
          }

          this._marketplacePackages.next(allPkgs);
          this._installedPackages.next(installedPkgs);
          this._externalPackages.next(extPkgs);

        }).catch((error) => console.log(error));
      }).catch((error) => console.log(error));
    }).catch((error) => console.log(error));
  }
}

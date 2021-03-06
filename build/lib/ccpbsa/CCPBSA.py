import sys
import os
import shutil
import subprocess
#from tqdm import tqdm
import pandas as pd
import numpy as np
import pymol 
import time
pymol.finish_launching(['pymol', '-Qc'])
cmd = pymol.cmd

def get_lj(*files):
    """Get the tail of a list of log files to extract the mean value of the
    Lennard-Jones Energy.
    """
    for f in files:
        with open(f, 'r') as ljlog:
            unparsed = ljlog.readlines()
            onefour = next(i for i in unparsed if 'LJ-14' in i).split()[1]
            sr = next(i for i in unparsed if 'LJ (SR)' in i).split()[2]

            yield float(onefour), float(sr)


def get_electro(*files):
    """Get the tail of a list of log files to extract the mean value of the
    Coulomb Energy.
    """
    for f in files:
        with open(f, 'r') as solvlog:
            unparsed = solvlog.readlines()
            coul = next(i for i in unparsed if 'Coulombic' in i).split()[6]
            solv = next(i for i in unparsed if 'Solvation' in i).split()[5]

            yield float(coul), float(solv)


def get_area(*files):
    for f in files:
        with open(f, 'r') as arealog:
            unparsed = arealog.readlines()
            area = unparsed[-1].split()[1]

            yield float(area)


def log(fname, proc_obj):
    """Write stdout and stderr of a process object to a file.
    """
    log_file = open(fname, 'a')

    if hasattr(proc_obj.stdout, 'decode'):
        print(proc_obj.stdout.decode('utf-8'))
        log_file.write(proc_obj.stdout.decode('utf-8'))

    if hasattr(proc_obj.stderr, 'decode'):
        print(proc_obj.stderr.decode('utf-8'))
        log_file.write(proc_obj.stderr.decode('utf-8'))

    log_file.close()


def int_in_str(*strings):
    """Takes strings as input and tries to find integers in them. Used to find
    the residue number in the mutation file.
    Returns a list of the integers found.
    """
    converted = [''.join([item for item in str_ if item.isdigit()]) \
        for str_ in strings]
    return converted


def flatten(lst=[]):
    """Unpacks a nested list. Does not care about the deepness of nesting since
    it calls itself recursively.
    """
    unpacked = []
    for i in list(lst):
        if type(i) is not str and type(i) is not int:
            unpacked.extend(flatten(list(i)))

        else:
            unpacked.append(i)

    return unpacked


def parse_flags(file_):
    """Parse the file containing the flags for CONCOORD and GROMACS. Returns a
    list of dictionaries with each program as key for the flags.
    """
    raw = open(file_, 'r').readlines()
    
#    Strip lines of comments.
    ignc = [i[:i.find(";")] for i in raw]
    ignc = [i.strip() for i in ignc if len(i) > 0]
    ignc = [i if i[0] != "[" else i for i in ignc ]

#    Find where programs are defined.
    progs = [i for i in ignc if i[0] == "["]
    idx = [ignc.index(i) for i in progs]

#    Pack program flags together with their program...
    parsed = [ignc[i:idx[idx.index(i)+1]] for i in idx[:-1]]
    parsed.append(ignc[idx[-1]:])

#    ...and make them into a dictionary. For easy reference later on.
    parsed = [{i[0][1:-1]: flatten([j.split("=")  \
        for j in i[1:]])} for i in parsed]

    parsed = dict(i for dict_ in parsed for i in dict_.items())

    input_ = {}
    for i, j in parsed.items():
        npt = "\n".join(j[j.index(k)+1] for k in j if k == '<<<')

        while '<<<' in j:

            for k in j:
                
                if k == '<<<':
                    idx = j.index(k)
                    parsed[i].pop(idx)
                    parsed[i].pop(idx)

        input_[i] = bytes(npt, 'utf-8')
#    print(input_)
    return parsed, input_


def parse_mutations(file_):
    """Returns a 3 dimensional pandas DataFrame of Mutations. Containing:
        - chain
        - amino acid (AA)
        - residue(number)
        - new amino acid (Mutation)
    Each new protein stores the information in a new row.
    Multiple mutations extend into the third dimension.
    """
    aa1 = list("ACDEFGHIKLMNPQRSTVWY")
    aa3 = "ALA CYS ASP GLU PHE GLY HIS ILE LYS LEU \
            MET ASN PRO GLN ARG SER THR VAL TRP TYR".split()
    aa123 = dict(zip(aa1,aa3))
    raw = open(file_, 'r').readlines()
    raw = [i for i in raw if i != '\n']

#    Remove whitespaces and empty lines
    raw = [i.replace(" ", "") for i in raw]
    raw = [i[:-1].split(",") for i in raw]
    maxmuts = max([len(i) for i in raw])
    muts = [tuple(i + [""] * (maxmuts - len(i))) for i in raw]

#    Index definition for the DataFrame.
    headers = ["Chain", "AA", "Residue", "Mutation"]

    mut_df = pd.DataFrame(
        columns=headers,
        index=pd.MultiIndex.from_tuples(muts)
    )

#    Fill the Chain column.
    for i, j in enumerate(raw):
        ext = maxmuts - len(j)

        chains = [k.split("_")[0] if len(k.split("_")) == 2 else "" for k in j]
        chains.extend([""] * ext)
        mut_df["Chain"][i] = chains

        aa = [k.split("_")[0][0] if len(k.split("_")) == 1 \
                else k.split("_")[1][0] for k in j]
        aa.extend([""] * ext)
        mut_df["AA"][:][i] = aa

        res = int_in_str(*j)
        res.extend([""] * ext)
        mut_df["Residue"][i] = res

        muts = [aa123[k[-1]] for k in j]
        muts.extend([""] * ext)
        mut_df["Mutation"][i] = muts

    return mut_df


def concoord(pipe, input_, *pdb, **flags):
    """Takes arbitrarily many .pdb files as input to generate structure
    ensembles using CONCOORD. Additional flags can be passed via a dictionary
    with the keys corresponding to the programs, i.e. \"dist\" and \"disco\".
    Verbosity can be controlled via the keyword \"verbosity\" which takes
    either 0 (do not show any messages) or 1 (show all messages).
    Returns the two process objects of dist and disco.
    """
    for p in pdb:
        os.chdir("/".join([i for i in p.split("/")[:-1]]+["."]))
        
        dist_input = [
            'dist',
            '-p', p, '-dssp', '/data/tom/dssp/./dsspcmbi', '-m', '100'
        ]
        if 'dist' in flags.keys():
            dist_input.extend(flags['dist'])

        disco_input = [
            'disco', '-i', '3000', '-t', '100', '-con', '700', '-bump', '-viol', '2'
        ]

        if 'disco' in flags.keys():
            disco_input.extend(flags['disco'])
       
        dist = subprocess.run(
            dist_input,
            input=input_,
            stdout=pipe,
            stderr=pipe
        )
        disco =subprocess.run(disco_input, stdout=pipe, stderr=pipe)

        return dist, disco


def gmx(prog, **kwargs):
    """Run a GROMACS program with its flags by passing them in a list object.
    kwargs are passed to the subprocess.run method.
    """
    while True:
        try:
            gmx = subprocess.run(['/data/dist/gromacs_2019/bin/gmx', '-quiet'] + prog, **kwargs)
        except PermissionError:
            time.sleep(120)
            continue
        break 

    if gmx.returncode == 0:
        return gmx
    else:
        print("Gromacs encountered fatal error")
        

    return gmx
 

def gro2pdb(gro, tpr, pdb, **kwargs):
    """Replace the original .pdb file by a .gro file. Preserves chains.
    Requires the originial .pdb file to still be there.
    """
    cmd.load(pdb)
    ori = cmd.get_chains()
    cmd.reinitialize()
    trjconv = gmx(
        ['trjconv', '-f', gro, '-s', tpr, '-o', pdb],
        **kwargs
#        input=b'0',
#        stdout=pipe,
#        stderr=pipe
    )
    cmd.load(pdb)
    replace = cmd.get_chains()

    for n, c in enumerate(ori):
        cmd.alter('chain %s' % replace[n], 'chain="%s"' % c)

    cmd.save(pdb)
    cmd.reinitialize()

    return trjconv


def filecheck(*strs):
    """Checks whether or not a string is a valid path to a file. Relative or
    absolute path does not matter. Yields the absolute path if the file was
    found
    """
    start = os.getcwd()

    for s in strs:
        splt = s.split("/")
        f = splt[-1]
        p = "/".join(splt[:-1]+["."])

        try:
            os.chdir(p)

            if f in os.listdir():
                yield s, os.getcwd() + "/" + f

        except FileNotFoundError:
            pass

        os.chdir(start)


class DataGenerator:
    """Main class to make CC/PBSA work. Creates a directory with the name of
    the wildtype (wt) protein and subdirectories for each structure ensemble.
    """
    def __init__(
        self,
        wtpdb, # wild type .pdb file
        mutlist, # list of mutations
        flags, # file specifying the flags for CONCOORD and GROMACS
        spmdp,
        dummy,
        verbosity=0
    ):  
        print(dummy)
        if verbosity == 0:
            self.pipe = {
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE
            }

        elif verbosity == 1:
            self.pipe = {
                'stdout': None,
                'stderr': None
            }

        else:
            raise ValueError

        self.wtpdb = os.getcwd() + "/" + wtpdb
        wtname = wtpdb.split('/')[-1]
        self.wt = wtname[:wtname.find(".pdb")]
        self.flags, self.input = parse_flags(flags)
        self.n = len(self)
        self.flags.setdefault("disco", []).extend(["-op", ""])
#        self.mut_df = parse_mutations(mutlist)
#        self.wds = [self.wt]
#        self.wds.extend(["+".join([j for j in i if len(j) > 0]) \
#            for i in self.mut_df.index])

        cmd.load(self.wtpdb)
        self.chains = cmd.get_chains()
        cmd.reinitialize()
        if not dummy:
            self.mut_df = parse_mutations(mutlist)
            self.wds = [self.wt]
            self.wds.extend(["+".join([j for j in i if len(j) > 0]) \
                    for i in self.mut_df.index])
            self.initdir(spmdp)
            self.do_mutate()
       
        else:
            self.wds = [self.wt]
            self.initdir(spmdp)


        self.spmdp = self.maindir + "/" + spmdp.split("/")[-1]


    def initdir(self, spmdp):
        """Creates the directory and filesystem for the structures, called
        automatically by __init__ if not surpressed.
        """
#        Create the directory for data generation.
        
        try:
            os.mkdir(self.wt)
            os.chdir(self.wt)

        except FileExistsError:
            newdir = input("Directory already exists. Enter a new name:\n")
            os.mkdir(newdir)
            os.chdir(newdir)

        self.maindir = os.getcwd()
        os.mkdir(self.wt)
        shutil.copy(self.wtpdb, self.wt)

        for k, v in self.flags.items():
            files = list(i for i in filecheck(*v))

            for ori, abs_ in files:
                shutil.copy(abs_, self.maindir)
                v[v.index(ori)] = self.maindir+"/"+abs_.split("/")[-1]
                self.flags[k] = v

#        Copy all parameter files into the main directory. And update new file
#        locations.
        os.chdir('..')

        shutil.copy(spmdp, self.maindir)

        os.chdir(self.maindir)


    def __len__(self):
        """Returns the number of structures that should be generated by
        CONCOORD.
        """
        try:
            n_idx = self.flags['disco'].index('-n')
            return int(self.flags['disco'][n_idx+1])

        except ValueError:
            return 300

    def mefinish(self):
        with open("multienergy_finished.txt", "w") as f:
            f.write("")


    def do_mutate(self):
        """Create directories for each mutation and save the .pdb file in
        there. Requires the mut_df attribute.
        """
        for i in range(len(self.mut_df.index)):
            cmd.load(self.wtpdb)
            cmd.wizard('mutagenesis')

            for j in range(len(self.mut_df["Residue"][i])):
                cmd.get_wizard().do_select('///%s/%s' % (
                    self.mut_df["Chain"][i][j],
                    self.mut_df["Residue"][i][j],
                ))
                cmd.get_wizard().set_mode(self.mut_df["Mutation"][i][j])
                cmd.get_wizard().apply()

            os.mkdir(self.wds[i+1])
            cmd.save(self.wds[i+1] + "/" + self.wds[i+1] + ".pdb")
            cmd.reinitialize()


    def do_concoord(self, d):
        """Goes into the directories listed in self.wds and generates

        structure ensembles using CONCOORD. Each generated structure has its on
        directory one level down the directoy tree. Updates self.wds with the
        new structures
        """
        pdb = d.split("/")[-1] + ".pdb"


#        violsum = ['-viol', str(0.00022 * atoms + 1)]
        concoord(self.pipe['stdout'], self.input['dist'], pdb, **self.flags)

        for i in range(1, len(self)+1):
            os.mkdir(str(i))
            shutil.move(str(i) + '.pdb', str(i))


    def do_minimization(self, d):
        """Do energy minimization on the structures in self.wds. If the
        affinity is to be calculated, then an index file for the chains will be
        made and the chains specified in self.chains are minimized.
        """
        pdb = d.split("/")[-1] + ".pdb"
        print(self.input['grompp'])
        gmx(
            ['pdb2gmx'] + self.flags['pdb2gmx'] + ['-f', pdb],
            **self.pipe,
            input=self.input['pdb2gmx']
        )
        gmx(
            ['editconf'] + self.flags['editconf'],
            **self.pipe,
            input=self.input['editconf']
        )
        gmx(
            ['grompp'] + self.flags['grompp'] + ['-c', 'out.gro'],
            **self.pipe,
            input=self.input['grompp']
        )
        gmx(
            ['mdrun'] + self.flags['mdrun'],
            **self.pipe,
            input=self.input['mdrun']
        )


    def update_structs(self):
        """Use gro2pdb to convert (minimized) confout.gro files into .pdb files
        with the same name as the directory.
        """
        for d in self.wds:
            os.chdir(d)
            pdb = d.split("/")[-1] + ".pdb"
            gro2pdb(
                'confout.gro',
                'topol.tpr',
                pdb,
                **self.pipe,
                input=b'0'
            )
#            Remove hydrogens for CONCOORD.
            cmd.load(pdb)
            cmd.remove('hydrogens')
            cmd.save(pdb)
            cmd.reinitialize()

            os.chdir(self.maindir)


    def single_point(self):
        """Creates a single point .tpr file.
        """
        gromppflags = self.flags['grompp'].copy()
        idx = gromppflags.index('-f')
        gromppflags.pop(idx)
        gromppflags.pop(idx)
        gmx(
            [
                'grompp', '-f', self.spmdp,
                '-c', 'confout.gro',
                '-o', 'sp.tpr',
            ] + gromppflags,
            **self.pipe
        )


    def electrostatics(self):
        """Calculate the Coulomb and Solvation Energies of structures of the
        specified .tpr file prefix in the directories. By default the file
        should be named sp (Single Point).
        Parameters for this are stored in a separate file for gropbe. Reference
        it through the main parameter file for CC/PBSA.
        """
        
        chainselec = ",".join(str(i) for i in range(len(self.chains)))
        
        shutil.copy(self.flags['gropbe'][0], 'gropbe.prm')

        with open('gropbe.prm', 'a') as params:
            params.write("in(tpr,sp.tpr)")

        while True:
            try:
                with open('/data/dist/gromacs_2019/lib/libgromacs.so.4', 'r') as f:
                    f.close()
                    print('shared library was accessible')
            except IOError:
                print('library could not be accessed')
                time.sleep(120)
                continue
            break

        print(os.getcwd())
        gropbe = subprocess.run(
            ["/data/tom/GroPBS-Make-3/./gropbe", 'gropbe.prm'],
            input=bytes(chainselec, 'utf-8'),
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
#        gropbe.stderr = None
        log("solvation.log", gropbe)


        if self.pipe['stdout'] == None:
            print(gropbe.stdout.decode('utf-8'))


    def lj(self):
        """Calculate the Lennard-Jones Energy based on a sp.tpr
        """
        gmx(
            [
                'mdrun', '-s', 'sp.tpr',
                '-rerun', 'confout.gro',
                '-deffnm', 'sp',
                '-nt', '1'
            ],
            **self.pipe
        )
        lj = gmx(
            ['energy', '-f', 'sp.edr', '-sum', 'yes'],
            input=b'5 7',
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        lj.stderr = None
        log("lj.log", lj)

        if self.pipe['stdout'] == None:
            print(lj.stdout.decode('utf-8'))


    def area(self):
        """Calculate the solvent accessible surface area and saves it to
        area.xvg. If the mode is set to affinity, only the wt protein structure
        ensemble will be used and the values for the interaction surface will
        be written into the .xvg file
        """
        gmx(['sasa', '-s', 'confout.gro'], input=b'0', **self.pipe)


    def schlitter(self, en):
        """Calculates an upper limit of the entropy according to Schlitter's
        formula. Used in .fullrun() if the mode is stability
        """
        trjcat = ['trjcat', '-cat', 'yes', '-f']
        covar = ['covar', '-f', 'trajout.xtc', '-nopbc', '-s']
        anaeig = ['anaeig', '-v', 'eigenvec.trr', '-entropy', '-s']

        trrs = [self.maindir+'/'+en+'/%d/traj.trr' % (n+1)
            for n in range(len(self))]

        gmx(trjcat+trrs, **self.pipe)
        gmx(
            covar+[self.maindir+'/'+en+"/topol.tpr"],
            input=self.input['covar'],
            **self.pipe
        )
        entropy = gmx(
            anaeig + [self.maindir+'/'+en+"/topol.tpr"],
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        log('entropy.log', entropy)

        if self.pipe['stdout'] == None:
            print(entropy.stdout.decode('utf-8'))


    def fullrun(self):
        """Use all of the default behaviour to generate the data. Not supported
        by multiprocessing. Just for quick tests within the library code.
        """
        print("Minimizing starting structures")
        for d in tqdm(self.wds):
            os.chdir(d)

            try:
                self.do_minimization(d)

            except KeyError:
                raise Exception("Missing flags for GROMACS, check flags file")

            os.chdir(self.maindir)

        print("Updating Structures.")
        self.update_structs()

        print("Generating CONCOORD structure ensembles.")
        for d in tqdm(self.wds):
            os.chdir(d)

            try:
                self.do_concoord(d)
                
            except FileNotFoundError:
                raise Exception("Your CONCOORD run failed!") 

            os.chdir(self.maindir)

        ensembles = self.wds.copy()
        self.wds = [d+'/'+str(i) for d in self.wds \
                for i in range(1, len(self)+1)]

        print("Minimizing structures and extract values.")
        for d in tqdm(self.wds):
            os.chdir(d)
            self.do_minimization(d)
            self.single_point()
            self.electrostatics()
            self.lj()
            self.area()
            os.chdir(self.maindir)

        print("Calculating Entropy of structure ensembles.") 
        for en in tqdm(ensembles):
            os.chdir(en)
            self.schlitter(en)
            os.chdir(self.maindir)


    def no_concoord(self):
        """Get energy values without running CONCOORD to ignore the flexibility
        contribution to the energy term. Very fast alternative. Not supported
        by multiprocessing.
        """
        self.n = 0
        print("Minimizing structures and extract values.")
        for d in tqdm(self.wds):
            os.chdir(d)
            self.do_minimization(d)
            self.single_point()
            self.electrostatics()
            self.lj()
            self.area()
            os.chdir(self.maindir)
        

class AffinityGenerator(DataGenerator):
    """Subclassed from DataGenerator to add additional procedures to calculate
    the affinity changes in mutated proteins
    """
    def __init__(
        self,
        wtpdb,
        mutlist,
        flags,
        chaingrp,
        spmdp,
        dummy,
        verbosity=0
    ):
        self.grp1 = chaingrp
        cmd.load(wtpdb)
        self.chains = cmd.get_chains()
        self.grp2 = "".join([c for c in cmd.get_chains() if c not in chaingrp])
        cmd.reinitialize()
        super().__init__(
           wtpdb=wtpdb,
           mutlist=mutlist,
           flags=flags,
           spmdp=spmdp,
           verbosity=verbosity,
           dummy=dummy
        )


    def split_chains(self, d):
        """Split the .pdb file into two new .pdb files as specified in the
        chaingrp argument. only one group needs to be specified. The leftover
        chains automatically form the second group.
        """
        pdb = d.split('/')[-1]
        cmd.load(pdb+'.pdb')
        cmd.split_chains()
        print('selfgrp1: ', self.grp1)
        print('selfgrp2: ', self.grp2)
        save1 = ', '.join([pdb+'_'+i for i in self.grp1])
        save2 = ', '.join([pdb+'_'+i for i in self.grp2])
        print('save1:', save1)
        print('save2:', save2)
        cmd.save(self.grp1+'.pdb', save1)
        cmd.save(self.grp2+'.pdb', save2)
        cmd.reinitialize()


    def do_minimization_chains(self):
        """Go into all the directories and minimize the .pdb files of the
        unbounded proteins instead.
        """
        fn = self.grp1
        gmx(
            ['pdb2gmx'] + self.flags['pdb2gmx'] + [
                '-f', fn+'.pdb', '-o', fn+'.gro', '-p', fn + '_topol.top'
            ],
            **self.pipe
        )
        gmx(
            ['editconf'] + self.flags['editconf'] + [
                '-f', fn+'.gro', '-o', fn+'.gro'
            ],
            **self.pipe,
            input=self.input['editconf']
        )
        gmx(
            ['grompp'] + self.flags['grompp'] + [
                '-c', fn+'.gro', '-o', fn+'.tpr', '-p', fn + '_topol.top'
            ],
            **self.pipe,
            input=self.input['grompp']
        )
        gmx(
            ['mdrun'] + self.flags['mdrun'] + ['-deffnm', fn],
            **self.pipe,
            input=self.input['mdrun']
        )

        fn2 = self.grp2
        gmx(
            ['pdb2gmx'] + self.flags['pdb2gmx'] + [
                '-f', fn2+'.pdb', '-o', fn2+'.gro', '-p', fn2 + '_topol.top'
            ],
            **self.pipe
        )
        gmx(
            ['editconf'] + self.flags['editconf'] + [
                '-f', fn2+'.gro', '-o', fn2+'.gro'
            ],
            **self.pipe,
            input=self.input['editconf']
        )
        gmx(
            ['grompp'] + self.flags['grompp'] + [
                '-c', fn2+'.gro', '-o', fn2+'.tpr', '-p', fn2 + '_topol.top'
            ],
            **self.pipe,
            input=self.input['grompp']
        )
        gmx(
            ['mdrun'] + self.flags['mdrun'] + ['-deffnm', fn2],
            **self.pipe,
            input=self.input['mdrun']
        )


    def single_point_chains(self):
        """Creates a single point .tpr file of the single groups.
        """
        gromppflags = self.flags['grompp'].copy()
        idx = gromppflags.index('-f')
        gromppflags.pop(idx)
        gromppflags.pop(idx)
        gmx(
            [
                'grompp', '-f', self.spmdp,
                '-c', self.grp1+'.gro',
                '-p', self.grp1+'_topol.top',
                '-o', self.grp1+'_sp.tpr',
            ] + gromppflags,
            **self.pipe
        )
        gmx(
            [
                'grompp', '-f', self.spmdp,
                '-c', self.grp2+'.gro',
                '-p', self.grp2+'_topol.top',
                '-o', self.grp2+'_sp.tpr',
            ] + gromppflags,
            **self.pipe
        )


    def electrostatics_chains(self):
        """Calculate the Coulomb and Solvation Energy based on the single
        point .tpr files of the chain groups. Parameters are stored in a
        separate file for gropbe. Reference it through the main parameter file
        for CC/PBSA.
        """
        chainselec = ",".join(str(i) for i in range(len(self.grp1)))

        shutil.copy(self.flags['gropbe'][0], 'gropbe.prm')

        with open('gropbe.prm', 'a') as params:
            params.write("in(tpr,%s_sp.tpr)" % self.grp1)
        
        while True:
            try:
                with open('/data/dist/gromacs_2019/lib/libgromacs.so.4', 'r') as f:
                    f.close()
                    print('shared library was accessible')
            except IOError:
                print('library could not be accessed')
                time.sleep(120)
                continue
            break

        print(os.getcwd())
        gropbe = subprocess.run(
            ["/data/tom/GroPBS-Make-3/./gropbe", 'gropbe.prm'],
            input=bytes(chainselec, 'utf-8'),
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        log("%s_solvation.log" % self.grp1, gropbe)

        if self.pipe['stdout'] == None:
            print(gropbe.stdout.decode('utf-8'))
        
        chainselec = ",".join(str(i) for i in range(len(self.grp2)))

        shutil.copy(self.flags['gropbe'][0], 'gropbe.prm')

        with open('gropbe.prm', 'a') as params:
            params.write("in(tpr,%s_sp.tpr)" % self.grp2)
        while True:
            try:
                with open('/data/dist/gromacs_2019/lib/libgromacs.so.4', 'r') as f:
                    f.close()
                    print('shared library was accessible')
            except IOError:
                print('library could not be accessed')
                time.sleep(120)
                continue
            break   

        print(os.getcwd())
        gropbe = subprocess.run(
            ["/data/tom/GroPBS-Make-3/./gropbe", 'gropbe.prm'],
            input=bytes(chainselec, 'utf-8'),
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        log("%s_solvation.log" % self.grp2, gropbe)

        if self.pipe['stdout'] == None:
            print(gropbe.stdout.decode('utf-8'))


    def lj_chains(self):
        """Calculate the Lennard-Jones Energy based on the sp.tpr of the
        unbound proteins
        """
        gmx([
            'mdrun', '-s', self.grp1+'_sp.tpr',
            '-rerun', self.grp1+'.gro',
            '-deffnm', self.grp1+'_sp',
            '-nt', '1'
        ])
        lj = gmx(
            ['energy', '-f', self.grp1+'_sp.edr', '-sum', 'yes'],
            input=b'5 7',
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        lj.stderr = None
        log(self.grp1+"_lj.log", lj)

        if self.pipe['stdout'] == None:
            print(lj.stdout.decode('utf-8'))

        gmx([
            'mdrun', '-s', self.grp2+'_sp.tpr',
            '-rerun', self.grp2+'.gro',
            '-deffnm', self.grp2+'_sp',
            '-nt', '1'
        ])
        lj = gmx(
            ['energy', '-f', self.grp2+'_sp.edr', '-sum', 'yes'],
            input=b'5 7',
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        lj.stderr = None
        log("".join(self.grp2)+"_lj.log", lj)

        if self.pipe['stdout'] == None:
            print(lj.stdout.decode('utf-8'))


    def area(self):
        """Calculate the interaction area of the wildtype protein.
        """
        sasa = ['sasa', '-s']

        os.chdir(self.wt)

        if self.n > 0:

            for i in range(1, len(self)+1):
                os.chdir(str(i))
                gmx(sasa + ['confout.gro'], input=b'0')
                gmx(
                    sasa + [self.grp1 + '.gro', '-o', self.grp1+'_area.xvg'],
                    input=b'0',
                    **self.pipe
                )
                gmx(
                    sasa + [self.grp2 + '.gro', '-o', self.grp2+'_area.xvg'],
                    input=b'0',
                    **self.pipe
                )
                os.chdir('..')

        else: 
            gmx(sasa + ['confout.gro'], input=b'0')
            gmx(
                sasa + [self.grp1 + '.gro', '-o', self.grp1+'_area.xvg'],
                input=b'0',
                **self.pipe
            )
            gmx(
                sasa + [self.grp2 + '.gro', '-o', self.grp2+'_area.xvg'],
                input=b'0',
                **self.pipe
            )

        os.chdir(self.maindir)


    def fullrun(self):
        """Generate all the data for DataCollector.
        """
        print("Minimizing starting structures")
        for d in tqdm(self.wds):
            os.chdir(d)
            super().do_minimization(d)
            os.chdir(self.maindir)
        
        super().update_structs()

        print("Generating CONCOORD structure ensembles.")
        for d in tqdm(self.wds):
            os.chdir(d)
            self.do_concoord(d)
            os.chdir(self.maindir)

        self.wds = [d+'/'+str(i) for d in self.wds \
                for i in range(1, len(self)+1)]

        print("Minimizing structures and extract values of bounded proteins")
        for d in tqdm(self.wds):
            os.chdir(d)
            super().do_minimization(d)
            super().single_point()
            super().electrostatics()
            super().lj()
            os.chdir(self.maindir)

        print("Minimizing structures and extract values of unbounded proteins")
        for d in tqdm(self.wds):
            os.chdir(d)
            self.split_chains(d)
            self.do_minimization_chains()
            self.single_point_chains()
            self.electrostatics_chains()
            self.lj_chains()
            os.chdir(self.maindir)
        
        self.area()


    def no_concoord(self):
        """Get energy values without running CONCOORD to ignore the flexibility
        contribution to the energy term. Very fast alternative.
        """
        print("Minimizing structures and extract values of bounded proteins")
        for d in tqdm(self.wds):
            os.chdir(d)
            super().do_minimization(d)
            super().single_point()
            super().electrostatics()
            super().lj()
            os.chdir(self.maindir)

        print("Minimizing structures and extract values of unbounded proteins")
        for d in tqdm(self.wds):
            os.chdir(d)
            self.split_chains(d)
            self.do_minimization_chains()
            self.single_point_chains()
            self.electrostatics_chains()
            self.lj_chains()
            os.chdir(self.maindir)
        
        self.area()


class DataCollector:
    """After a run of DataGenerator, the object can be parsed to this class to
    search for the relevant files in which energy values are supposed to be
    stored. Also contains methods to create .csv tables for calculation of
    folding free energy differences between wildtype and mutant protein.
    """
    aa1 = list("ACDEFGHIKLMNPQRSTVWY")
    aa3 = "ALA CYS ASP GLU PHE GLY HIS ILE LYS LEU MET ASN PRO GLN ARG SER THR VAL TRP TYR".split()
    aa123 = dict(zip(aa1,aa3))
    aa321 = dict(zip(aa3,aa1))

    def __init__(self, data_obj):
        """Pass the DataGenerator object to initialize. This way all the
        directories that contains the data is known without much searching.
        """
        self.maindir = data_obj.maindir
        self.wds = data_obj.wds
        os.chdir(self.maindir)

        self.n = data_obj.n
        self.mut_df = data_obj.mut_df
        self.wt = data_obj.wt

        for i, k in enumerate(self.mut_df["Mutation"].index):
 
            for j, l in enumerate(k):
                mut = self.mut_df["Mutation"][i][j]
        
                if len(mut) > 0:
                    self.mut_df["Mutation"][i][j] = self.aa321[mut]

        idx = next(os.walk('.'))[1]
        self.G_mean = pd.DataFrame(0.0, 
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'SAS', '-TS'],
            index=idx
        )

        if self.n > 0:
            idx = pd.MultiIndex.from_tuples(
                [(i, j) for i in idx for j in range(1, len(self)+1)]
            )

        self.G = pd.DataFrame(0.0, 
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'SAS'],
            index=idx
        )
        self.dG = self.G_mean.drop(self.wt)
        self.ddG = pd.DataFrame(0.0,
            columns=['CALC', 'SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'SAS', '-TS'],
            index=self.dG.index
        )


    def __len__(self):
        """Returns the number of structures generated by CONCOORD
        """
        return self.n
        

    def search_lj(self):
        """Find the files in which the Lennard-Jones energies are supposed to
        be written in and save the parsed values in self.G.
        """
        for i in self.G.index:

            if self.n > 0:
                d = "/".join([str(j) for j in i])
                os.chdir(d)

            else:
                os.chdir(i)

            try:
                LJ = next(get_lj('lj.log'))
                
            except:
                LJ = [np.NaN, np.NaN]

            self.G['LJ (1-4)'][i] = LJ[0]
            self.G['LJ (SR)'][i] = LJ[1]

            os.chdir(self.maindir)


    def search_electro(self):
        """Find the file in which the Coulomb energies are supposed to be
        written in and save the parsed values in G.
        """
        for i in self.G.index:

            if self.n > 0:
                d = "/".join([str(j) for j in i])
                os.chdir(d)

            else:
                os.chdir(i)

            try:
                vals = next(get_electro('solvation.log'))

            except RuntimeError:
                vals = [np.NaN, np.NaN]

            self.G['COUL'][i] = vals[0]
            self.G['SOLV'][i] = vals[1]

            os.chdir(self.maindir)


    def search_area(self):
        """Find the files in which the (interaction-)area (normally area.xvg)
        potential are supposed to be written in and save the parsed values in
        G.
        """
        for i in self.G.index:

            if self.n > 0:
                d = "/".join([str(j) for j in i])
                os.chdir(d)

            else:
                os.chdir(i)

            try:
                self.G['SAS'][i] = next(get_area('area.xvg'))

            except:
                self.G['SAS'][i] = np.NaN

            os.chdir(self.maindir)


    def search_entropy(self):
        """Find the files in which the entropy according the Schlitter's
        formula are supposed to be written in and save the parsed values in
        self.G.
        """
        head = "head -n 1 entropy.log".split()
        for i in self.G_mean.index:
            os.chdir(i)

            try:
                entropy = subprocess.run(head, stdout=subprocess.PIPE)
                entropy = entropy.stdout.decode('utf-8')
                valstart = entropy.index('is ')+3
                valend = entropy.index(' J/mol K')
                entropy = float(entropy[valstart:valend])/1000 # J/mol K-->kJ/mol K
                self.G_mean['-TS'][i] = np.array(-298.15 * entropy)

            except:
                self.G_mean['-TS'][i] = np.NaN

            os.chdir(self.maindir)


    def search_data(self):
        """Use all of the searching methods to fill out the energy table.
        Returns the DataFrame object.
        """
        self.search_lj()
        self.search_electro()
        self.search_area()
        self.search_entropy()

        for c in self.G.columns:
            
            for i in self.G_mean.index:
                self.G_mean.loc[i, c] = self.G.loc[i, c].mean()

        return self.G_mean, self.G


    def dstability(self, gxg_table):
        """Calculate the free energy difference between folded and unfolded
        state based on the energy table passed. ddstability operates
        independent of this function. This is just used for additional info.
        """
        gxgtable = pd.read_csv(gxg_table, index_col=0)
        self.dG_unfld = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'SAS', '-TS'],
            index=[]
        )

        for c in gxgtable.columns:

            for i in self.mut_df.index:
                mut = [j for j in self.mut_df.loc[i, "Mutation"] if len(j) > 0]
                wt = [j for j in self.mut_df.loc[i, "AA"] if len(j) > 0]

                unfld = [
                    gxgtable[c]["G%sG" % mut[j]] - gxgtable[c]["G%sG" % wt[j]] \
                        for j in range(len(mut))
                ]
                dfi = "+".join([j for j in i if len(j) > 0])
                self.dG_unfld.loc[dfi, c] = sum(unfld)
                self.dG_unfld.to_csv("dG_unfold.csv")

            for i in self.dG.index:
                self.dG.loc[i, c] = self.G_mean.loc[i, c] - self.G_mean.loc[self.wt, c]

        return self.dG, self.dG_unfld


    def ddstability(self):
        """Calculate the folding free energy difference. For this stability
        calculation, a table with values of GXG tripeptides needs to be
        supplied.
        """
        for c in self.ddG.columns[1:]:

            for i in self.ddG.index:
                self.ddG.loc[i, c] = self.dG.loc[i, c] - self.dG_unfld.loc[i, c]


        for i in self.ddG.index:
            self.ddG["CALC"][i] = sum(self.ddG.loc[i, "SOLV":])
        
        return self.ddG

    def fitstability(self, alpha, beta, gamma, tau):
        """Multiply the column of each energy contribution by a certain value.
        """
        self.ddG["SOLV"] *= alpha
        self.ddG["COUL"] *= alpha
        self.ddG["LJ (1-4)"] *= beta
        self.ddG["LJ (SR)"] *= beta
        self.ddG["SAS"] *= gamma
        self.ddG["-TS"] *= tau

        for i in self.ddG.index:
            self.ddG["CALC"][i] = sum(self.ddG.loc[i, "SOLV":])

        return self.ddG

class WTCollector:
    def __init__(self, data_obj):

        self.maindir = data_obj.maindir
        os.chdir(self.maindir)
        self.n = data_obj.n
        self.wt = data_obj.wt
        self.grp1 = data_obj.grp1
        self.grp2 = data_obj.grp2
        idx = next(os.walk('.'))[1]
        self.G_bound_mean = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=idx
        )
        self.G_grp1_mean = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=idx
        )
        self.G_grp2_mean = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=idx
        )

        if self.n > 0:
            idx = pd.MultiIndex.from_tuples(
                [(i, j) for i in idx for j in range(1, len(self)+1)]
            )

        self.G_bound = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=idx
        )
        self.G_grp1 = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=self.G_bound.index
        )
        self.G_grp2 = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=self.G_bound.index
        )

    def __len__(self):
        return self.n

    def search_lj(self):
        """Find the files in which the Lennard-Jones energies are supposed to
        be written in and save the parsed values in the respective self.G table.
        """
        for i in self.G_bound.index:

            if self.n > 0:
                d = "/".join([str(j) for j in i])
                os.chdir(d)

            else:
                os.chdir(i)
            try:
                vals = next(get_lj('lj.log'))
            except RuntimeError:
                vals = [np.NaN, np.NaN]

            self.G_bound['LJ (1-4)'][i] = vals[0]
            self.G_bound['LJ (SR)'][i] = vals[1]
            try:
                vals = next(get_lj('%s_lj.log' % self.grp1))
                print(i)
            except RuntimeError:
                vals = [np.NaN, np.NaN]

#            vals = next(get_lj('%s_lj.log' % self.grp1))
            self.G_grp1['LJ (1-4)'][i] = vals[0]
            self.G_grp1['LJ (SR)'][i] = vals[1]
            try:
                vals = next(get_lj('%s_lj.log' % self.grp2))
            except RuntimeError:
                vals = [np.NaN, np.NaN]
#            vals = next(get_lj('%s_lj.log' % self.grp2))
            self.G_grp2['LJ (1-4)'][i] = vals[0]
            self.G_grp2['LJ (SR)'][i] = vals[1]

            os.chdir(self.maindir)

    def search_electro(self):
        """Find the files in which the Solvation energies are supposed to be
        written in and save the parsed values in the respective self.G table.
        """
        for i in self.G_bound.index:
            print('search_electro: ', i)

            if self.n > 0:
                d = "/".join([str(j) for j in i])
                os.chdir(d)

            else:
                os.chdir(i)

            try:
                vals = next(get_electro('solvation.log'))
            except RuntimeError:
                vals = [np.NaN, np.NaN]
            self.G_bound['COUL'][i] = vals[0]
            self.G_bound['SOLV'][i] = vals[1]

            try:
                vals = next(get_electro('%s_solvation.log' % self.grp1))
            except RuntimeError:
                vals = [np.NaN, np.NaN]
            self.G_grp1['COUL'][i] = vals[0]
            self.G_grp1['SOLV'][i] = vals[1]

            try:
                vals = next(get_electro('%s_solvation.log' % self.grp2))
            except RuntimeError:
                vals = [np.NaN, np.NaN]
            self.G_grp2['COUL'][i] = vals[0]
            self.G_grp2['SOLV'][i] = vals[1]

            os.chdir(self.maindir)

    def search_area(self):
        """Get the protein-protein interaction surface (PPIS) of the wildtype
        and store it in the ddG table since mutant values are not required.
        """
        os.chdir(self.wt)

        if self.n > 0:

            for i in range(len(self)):
                os.chdir(str(i+1))

                try:
                    print('search_area: ',self.wt, i)
                    cmplx = next(get_area("area.xvg"))
                    grp1 = next(get_area("%s_area.xvg" % self.grp1))
                    grp2 = next(get_area("%s_area.xvg" % self.grp2))
                except RuntimeError:
                    cmplx = np.NaN
                    grp1 = np.NaN
                    grp2 = np.NaN

                self.G_bound.loc[self.wt, i+1]['PPIS'] = cmplx
                self.G_grp1.loc[self.wt, i+1]['PPIS'] = grp1
                self.G_grp2.loc[self.wt, i+1]['PPIS'] = grp2

                os.chdir('..')

        else:
            cmplx = next(get_area("area.xvg"))
            grp1 = next(get_area("%s_area.xvg" % self.grp1))
            grp2 = next(get_area("%s_area.xvg" % self.grp2))

            self.G_bound.loc[self.wt, i+1]['PPIS'] = cmplx
            self.G_grp1.loc[self.wt, i+1]['PPIS'] = grp1
            self.G_grp2.loc[self.wt, i+1]['PPIS'] = grp2

        os.chdir(self.maindir)

    def search_data(self):
        """Use all of the searching methods to fill out the energy table.
        Returns the DataFrame object.
        """
        self.search_lj()
        self.search_electro()
        self.search_area()

        for c in self.G_bound.columns:

            for i in self.G_bound_mean.index:
                self.G_bound_mean.loc[i, c] = self.G_bound.loc[i, c].mean()
                self.G_grp1_mean.loc[i, c] = self.G_grp1.loc[i, c].mean()
                self.G_grp2_mean.loc[i, c] = self.G_grp2.loc[i, c].mean()


        self.G_bound_mean['PPIS'] = self.G_bound.loc[self.wt, 'PPIS'].mean()

        return self.G_bound_mean, self.G_grp1_mean, self.G_grp2_mean

    def merge(self):
        
        combined = pd.concat([self.G_bound_mean, self.G_grp1_mean, self.G_grp2_mean])
        combined.to_csv('wt_values.csv', index=False)




class AffinityCollector:
    """After a fullrun of AffinityCollector, the object can be passed to this
    constructor to extract the energy values from the directory. A full search
    produces .csv files with values for the bounded and unbounded states for
    wildtype and mutations, aswell as the ddG values.
    """
    aa1 = list("ACDEFGHIKLMNPQRSTVWY")
    aa3 = "ALA CYS ASP GLU PHE GLY HIS ILE LYS LEU MET ASN PRO GLN ARG SER THR VAL TRP TYR".split()
    aa123 = dict(zip(aa1,aa3))
    aa321 = dict(zip(aa3,aa1))

    def __init__(self, data_obj, wt=False):
        """Pass a AffinityGenerator object to initialize.
        """
        self.maindir = data_obj.maindir
        os.chdir(self.maindir)

        self.n = data_obj.n
        self.mut_df = data_obj.mut_df
        self.wt = data_obj.wt
        self.grp1 = data_obj.grp1
        self.grp2 = data_obj.grp2

        for i, k in enumerate(self.mut_df["Mutation"].index):

            for j, l in enumerate(k):
                mut = self.mut_df["Mutation"][i][j]

                if len(mut) > 0:
                    self.mut_df["Mutation"][i][j] = self.aa321[mut]

        idx = next(os.walk('.'))[1]
        if not self.wt in idx:
            idx.extend(self.wt)
        self.G_bound_mean = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=idx
        )
        self.G_grp1_mean = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=idx
        )
        self.G_grp2_mean = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=idx
        )

        if self.n > 0:
            idx = pd.MultiIndex.from_tuples(
                [(i, j) for i in idx for j in range(1, len(self)+1)]
            )

        self.G_bound = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=idx
        )
        self.G_grp1 = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=self.G_bound.index
        )
        self.G_grp2 = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=self.G_bound.index
        )

        self.dG_bound = self.G_bound_mean.drop(self.wt)
        self.dG_unbound = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS'],
            index=self.dG_bound.index
        )
        self.ddG = pd.DataFrame(0.0,
            columns=['CALC', 'SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'PPIS', 'PKA'],
            index=self.dG_bound.index
        )


    def __len__(self):
        return self.n

    def search_lj(self, wt=False):
        """Find the files in which the Lennard-Jones energies are supposed to
        be written in and save the parsed values in the respective self.G table.
        """
        if not wt:
            index = self.G_bound.index
            for i in index:

                if self.n > 0:
                    d = "/".join([str(j) for j in i])
                    os.chdir(d)

                else:
                    os.chdir(i)
                try:
                    vals = next(get_lj('lj.log'))
                except RuntimeError or FileNotFoundError:
                    vals = [np.NaN, np.NaN]

                self.G_bound['LJ (1-4)'][i] = vals[0]
                self.G_bound['LJ (SR)'][i] = vals[1]
                try:
                    vals = next(get_lj('%s_lj.log' % self.grp1))
                except RuntimeError or FileNotFoundError:
                    vals = [np.NaN, np.NaN]

#            vals = next(get_lj('%s_lj.log' % self.grp1))
                self.G_grp1['LJ (1-4)'][i] = vals[0]
                self.G_grp1['LJ (SR)'][i] = vals[1]
                try:
                    vals = next(get_lj('%s_lj.log' % self.grp2))
                except RuntimeError or FileNotFoundError:
                    vals = [np.NaN, np.NaN]
#            vals = next(get_lj('%s_lj.log' % self.grp2))
                self.G_grp2['LJ (1-4)'][i] = vals[0]
                self.G_grp2['LJ (SR)'][i] = vals[1]

                os.chdir(self.maindir)
        else:
            index = next(os.walk('.'))[1]
            if self.wt in index:
                index.remove(self.wt)
            if self.n > 0:
                index = pd.MultiIndex.from_tuples(
                        [(i, j) for i in index for j in range(1, len(self)+1)]
                )

            
            for i in index:

                if self.n > 0:
                    d = "/".join([str(j) for j in i])
                    os.chdir(d)

                else:
                    os.chdir(i)
                try:
                    vals = next(get_lj('lj.log'))
                except RuntimeError or FileNotFoundError:
                    vals = [np.NaN, np.NaN]

                self.G_bound['LJ (1-4)'][i] = vals[0]
                self.G_bound['LJ (SR)'][i] = vals[1]
                try:
                    vals = next(get_lj('%s_lj.log' % self.grp1))
                except RuntimeError or FileNotFoundError:
                    vals = [np.NaN, np.NaN]

#            vals = next(get_lj('%s_lj.log' % self.grp1))
                self.G_grp1['LJ (1-4)'][i] = vals[0]
                self.G_grp1['LJ (SR)'][i] = vals[1]
                try:
                    vals = next(get_lj('%s_lj.log' % self.grp2))
                except RuntimeError or FileNotFoundError:
                    vals = [np.NaN, np.NaN]
#            vals = next(get_lj('%s_lj.log' % self.grp2))
                self.G_grp2['LJ (1-4)'][i] = vals[0]
                self.G_grp2['LJ (SR)'][i] = vals[1]

                os.chdir(self.maindir)



    def search_electro(self, wt=False):
        """Find the files in which the Solvation energies are supposed to be
        written in and save the parsed values in the respective self.G table.
        """
        if not wt:
            for i in self.G_bound.index:

                if self.n > 0:
                    d = "/".join([str(j) for j in i])
                    os.chdir(d)

                else:
                    os.chdir(i)

                try:
                    vals = next(get_electro('solvation.log'))
                except RuntimeError:
                    vals = [np.NaN, np.NaN]
                self.G_bound['COUL'][i] = vals[0]
                self.G_bound['SOLV'][i] = vals[1]

                try:
                    vals = next(get_electro('%s_solvation.log' % self.grp1))
                except RuntimeError:
                    vals = [np.NaN, np.NaN]
                self.G_grp1['COUL'][i] = vals[0]
                self.G_grp1['SOLV'][i] = vals[1]

                try:
                    vals = next(get_electro('%s_solvation.log' % self.grp2))
                except RuntimeError:
                    vals = [np.NaN, np.NaN]
                self.G_grp2['COUL'][i] = vals[0]
                self.G_grp2['SOLV'][i] = vals[1]

                os.chdir(self.maindir)
        else:
            index = next(os.walk('.'))[1]
            if self.wt in index:
                index.remove(self.wt)
            if self.n > 0:
                index = pd.MultiIndex.from_tuples(
                        [(i, j) for i in index for j in range(1, len(self)+1)]
                )

            for i in index:

                if self.n > 0:
                    d = "/".join([str(j) for j in i])
                    os.chdir(d)

                else:
                    os.chdir(i)

                try:
                    vals = next(get_electro('solvation.log'))
                except RuntimeError:
                    vals = [np.NaN, np.NaN]
                self.G_bound['COUL'][i] = vals[0]
                self.G_bound['SOLV'][i] = vals[1]

                try:
                    vals = next(get_electro('%s_solvation.log' % self.grp1))
                except RuntimeError:
                    vals = [np.NaN, np.NaN]
                self.G_grp1['COUL'][i] = vals[0]
                self.G_grp1['SOLV'][i] = vals[1]

                try:
                    vals = next(get_electro('%s_solvation.log' % self.grp2))
                except RuntimeError:
                    vals = [np.NaN, np.NaN]
                self.G_grp2['COUL'][i] = vals[0]
                self.G_grp2['SOLV'][i] = vals[1]

                os.chdir(self.maindir)

    def search_area(self):
        """Get the protein-protein interaction surface (PPIS) of the wildtype
        and store it in the ddG table since mutant values are not required.
        """
        os.chdir(self.wt)

        if self.n > 0:

            for i in range(len(self)):
                os.chdir(str(i+1))

                try:
                    cmplx = next(get_area("area.xvg"))
                    grp1 = next(get_area("%s_area.xvg" % self.grp1))
                    grp2 = next(get_area("%s_area.xvg" % self.grp2))

                    self.G_bound.loc[self.wt, i+1]['PPIS'] = cmplx
                    self.G_grp1.loc[self.wt, i+1]['PPIS'] = grp1
                    self.G_grp2.loc[self.wt, i+1]['PPIS'] = grp2

                except RuntimeError:
                    cmplx = np.NaN
                    grp1 = np.NaN
                    grp2 = np.NaN

                os.chdir('..')

#            self.G_bound_mean.loc[self.wt]['PPIS'] = grp1 + grp2 - cmplx

        else:
            cmplx = next(get_area("area.xvg"))
            grp1 = next(get_area("%s_area.xvg" % self.grp1))
            grp2 = next(get_area("%s_area.xvg" % self.grp2))

#            self.G_bound_mean.loc[self.wt]['PPIS'] = grp1 + grp2 - cmplx

            self.G_bound.loc[self.wt, i+1]['PPIS'] = cmplx
            self.G_grp1.loc[self.wt, i+1]['PPIS'] = grp1
            self.G_grp2.loc[self.wt, i+1]['PPIS'] = grp2
            
 
        os.chdir(self.maindir)


    def search_data(self, wt_values=[], wt=False):
        """Use all of the searching methods to fill out the energy table.
        Returns the DataFrame object.
        """
        if wt:
            self.search_lj(wt=True)
            self.search_electro(wt=True)
        else:
            self.search_lj()
            self.search_electro()
            self.search_area()

        for c in self.G_bound.columns:
 
            for i in self.G_bound_mean.index:
                self.G_bound_mean.loc[i, c] = self.G_bound.loc[i, c].mean()
                self.G_grp1_mean.loc[i, c] = self.G_grp1.loc[i, c].mean()
                self.G_grp2_mean.loc[i, c] = self.G_grp2.loc[i, c].mean()


        if wt:
            i = 0
            for c in self.G_bound.columns:
                self.G_bound_mean.at[self.wt, c] = wt_values[0][i]
                self.G_grp1_mean.at[self.wt, c] = wt_values[1][i]
                self.G_grp2_mean.at[self.wt, c] = wt_values[2][i]
                i = i+1

        else:
            self.G_bound_mean['PPIS'] = self.G_bound.loc[self.wt, 'PPIS'].mean()
            self.G_grp1_mean['PPIS'] = self.G_grp1.loc[self.wt, 'PPIS'].mean()
            self.G_grp2_mean['PPIS'] = self.G_grp2.loc[self.wt, 'PPIS'].mean()

        return self.G_bound_mean, self.G_grp1_mean, self.G_grp2_mean


    def daffinity(self):
        """Calculate the dG tables for the (un-)bounded state for the mutations
        by subtracting the wildtype values from it.
        """
        for c in self.dG_bound.columns:
            if c == 'PPIS':
                pass
            else:

                for i in self.dG_bound.index:
                    self.dG_bound.loc[i, c] = \
                        self.G_bound_mean.loc[i, c] - \
                        self.G_bound_mean.loc[self.wt, c]
            
                    self.dG_unbound.loc[i, c] = \
                        (self.G_grp1_mean.loc[i, c] - \
                        self.G_grp1_mean.loc[self.wt, c]) + \
                        (self.G_grp2_mean.loc[i, c] - \
                        self.G_grp2_mean.loc[self.wt, c])
        
        self.dG_bound = self.dG_bound.assign(PPIS = self.G_bound_mean.loc[self.wt]['PPIS'])
        unb_area = self.G_grp1_mean.loc[self.wt]['PPIS'] + self.G_grp2_mean.loc[self.wt]['PPIS']
        self.dG_unbound = self.dG_unbound.assign(PPIS = unb_area)


    def ddaffinity(self):
        """Calculate the binding free energy difference
        """
        for c in self.dG_bound.columns:

            for i in self.dG_unbound.index:
                self.ddG[c][i] = self.dG_bound[c][i] - self.dG_unbound[c][i]

        self.ddG['PPIS'] = self.ddG['PPIS'] / 2

        for i in self.ddG.index:
            self.ddG["CALC"][i] = sum(self.ddG.loc[i, "SOLV":]) 
#                + self.G_bound_mean['PPIS'][0]
#            self.ddG['PPIS'][i] = self.G_bound_mean['PPIS'][0]

    
    def fitaffinity(self, alpha, beta, gamma, c, pka=0):
        """Multiply the column of each energy contribution by a certain value.
        Add constants to values as in the paper.
        """
        self.ddG["SOLV"] *= alpha
        self.ddG["COUL"] *= alpha
        self.ddG["LJ (1-4)"] *= beta
        self.ddG["LJ (SR)"] *= beta
        self.ddG["PPIS"] = gamma*self.ddG["PPIS"] + c
        self.ddG["PKA"] = pka

        for i in self.ddG.index:
            self.ddG["CALC"][i] = sum(self.ddG.loc[i, "SOLV":])

        return self.ddG


class GXG(DataGenerator, DataCollector):
    """Prepares a directory for the creation/calculation of a GXG tripeptides
    energy table. This serves as an estimation of the energy difference of the
    unfolded state. Subclassed from DataGenerator and DataCollector.
    """
    def __init__(
        self,
        flags,
        spmdp,
        verbosity=0
    ):
        """In contrast to DataGenerator, this constructor does not require the
        wildtype .pdb file or a list of mutations.
        """
        if verbosity == 0:
            self.pipe = {
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE
            }

        elif verbosity == 1:
            self.pipe = {
                'stdout': None,
                'stderr': None
            }

        else:
            raise ValueError
        
        self.flags, self.input = parse_flags(flags)
        self.flags.setdefault("disco", []).extend(["-op", ""])
        self.chains = 'A'
        self.n = len(self)
        os.mkdir('GXG')
        os.chdir('GXG')
        self.maindir = os.getcwd()

        for x in self.aa1:
            gxg = 'G%sG' % x
            os.mkdir(gxg)
            cmd.fab(gxg)
            cmd.save('%s/%s.pdb' % (gxg, gxg))
            cmd.alter('chain ""', 'chains="A"')
            cmd.reinitialize()

        os.chdir('..')

        for k, v in self.flags.items():
            files = list(i for i in filecheck(*v))

            for ori, abs_ in files:
                shutil.copy(abs_, self.maindir)
                v[v.index(ori)] = self.maindir+"/"+abs_.split("/")[-1]
                self.flags[k] = v

        shutil.copy(spmdp, self.maindir)
        self.spmdp = self.maindir + "/" + spmdp.split("/")[-1]

        os.chdir(self.maindir)
        self.wds = ['G%sG' % x for x in self.aa1]
        idx = next(os.walk('.'))[1]
        self.G_mean = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'SAS', '-TS'],
            index=idx
        )
        idx = pd.MultiIndex.from_tuples(
            [(i, j) for i in idx for j in range(1, len(self)+1)]
        )
        self.G = pd.DataFrame(0.0,
            columns=['SOLV', 'COUL', 'LJ (1-4)', 'LJ (SR)', 'SAS'],
            index=idx
        )


    def create_table(self):
        """Creates the lookup table for the unfolded state in stability
        calculations.
        """
        self.fullrun()
        return self.search_data()


class ResumeCheckpoint_stability:
    """Restarts the program at energy calculations and skips directories
    where the calculations have finished.
    """
    def __init__(
        self,
        wtpdb, # wild type .pdb file
        mutlist, # list of mutations
        flags, # file specifying the flags for CONCOORD and GROMACS
        spmdp,
        ckpt,
        dummy,
        verbosity=0
    ):

        if verbosity == 0:
            self.pipe = {
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE
            }

        elif verbosity == 1:
            self.pipe = {
                'stdout': None,
                'stderr': None
            }

        else:
            raise ValueError

        self.wtpdb = os.getcwd() + "/" + wtpdb
        wtname = wtpdb.split('/')[-1]
        self.wt = wtname[:wtname.find(".pdb")]
        self.flags, self.input = parse_flags(flags)
        self.n = len(self)
        self.flags.setdefault("disco", []).extend(["-op", ""])
#        self.mut_df = parse_mutations(mutlist)
#        self.wds = [self.wt]
#        self.wds.extend(["+".join([j for j in i if len(j) > 0]) \
#            for i in self.mut_df.index])

        cmd.load(self.wtpdb)
        self.chains = cmd.get_chains()
        cmd.reinitialize()
        self.maindir = ckpt
        if not dummy:
            self.mut_df = parse_mutations(mutlist)
            self.wds = [self.wt]
            self.wds.extend(["+".join([j for j in i if len(j) > 0]) \
                    for i in self.mut_df.index])

        else:
            self.wds = [self.wt]
            self.maindir = ckpt
#            self.initdir(spmdp)


        self.spmdp = self.maindir + "/" + spmdp.split("/")[-1]

        try:
            shutil.copy(self.wtpdb, self.wt)
        except shutil.SameFileError:
            pass

        for k, v in self.flags.items():
            files = list(i for i in filecheck(*v))

            for ori, abs_ in files:
                try:
                    shutil.copy(abs_, self.maindir)
                except shutil.SameFileError:
                    pass
                v[v.index(ori)] = self.maindir+"/"+abs_.split("/")[-1]
                self.flags[k] = v

#        Copy all parameter files into the main directory. And update new file
#        locations.
        os.chdir('..')
        try:
            shutil.copy(spmdp, self.maindir)
        except shutil.SameFileError:
            pass

        os.chdir(self.maindir)


    def __len__(self):
        """Returns the number of structures that should be generated by
        CONCOORD.
        """
        try:
            n_idx = self.flags['disco'].index('-n')
            return int(self.flags['disco'][n_idx+1])

        except ValueError:
            return 300


    def do_minimization(self, d):
        """Do energy minimization on the structures in self.wds. If the
        affinity is to be calculated, then an index file for the chains will be
        made and the chains specified in self.chains are minimized.
        """
        pdb = d.split("/")[-1] + ".pdb"
        print(self.input['grompp'])
        gmx(
            ['pdb2gmx'] + self.flags['pdb2gmx'] + ['-f', pdb],
            **self.pipe,
            input=self.input['pdb2gmx']
        )
        gmx(
            ['editconf'] + self.flags['editconf'],
            **self.pipe,
            input=self.input['editconf']
        )
        gmx(
            ['grompp'] + self.flags['grompp'] + ['-c', 'out.gro'],
            **self.pipe,
            input=self.input['grompp']
        )
        gmx(
            ['mdrun'] + self.flags['mdrun'],
            **self.pipe,
            input=self.input['mdrun']
        )


    def single_point(self):
        """Creates a single point .tpr file.
        """
        gromppflags = self.flags['grompp'].copy()
        idx = gromppflags.index('-f')
        gromppflags.pop(idx)
        gromppflags.pop(idx)
        gmx(
            [
                'grompp', '-f', self.spmdp,
                '-c', 'confout.gro',
                '-o', 'sp.tpr',
            ] + gromppflags,
            **self.pipe
        )


    def electrostatics(self):
        """Calculate the Coulomb and Solvation Energies of structures of the
        specified .tpr file prefix in the directories. By default the file
        should be named sp (Single Point).
        Parameters for this are stored in a separate file for gropbe. Reference
        it through the main parameter file for CC/PBSA.
        """
        
        chainselec = ",".join(str(i) for i in range(len(self.chains)))
        
        shutil.copy(self.flags['gropbe'][0], 'gropbe.prm')

        with open('gropbe.prm', 'a') as params:
            params.write("in(tpr,sp.tpr)")
        
        while True:
            try:
                with open('/data/dist/gromacs_2019/lib/libgromacs.so.4', 'r') as f:
                    f.close()
                    print('shared library was accessible')
            except IOError:
                print('library could not be accessed')
                time.sleep(120)
                continue
            break

        gropbe = subprocess.run(
            ["/data/tom/GroPBS-Make-3/./gropbe", 'gropbe.prm'],
            input=bytes(chainselec, 'utf-8'),
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
#        gropbe.stderr = None
        log("solvation.log", gropbe)


        if self.pipe['stdout'] == None:
            print(gropbe.stdout.decode('utf-8'))


    def lj(self):
        """Calculate the Lennard-Jones Energy based on a sp.tpr
        """
        gmx(
            [
                'mdrun', '-s', 'sp.tpr',
                '-rerun', 'confout.gro',
                '-deffnm', 'sp',
                '-nt', '1'
            ],
            **self.pipe
        )
        lj = gmx(
            ['energy', '-f', 'sp.edr', '-sum', 'yes'],
            input=b'5 7',
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        lj.stderr = None
        log("lj.log", lj)

        if self.pipe['stdout'] == None:
            print(lj.stdout.decode('utf-8'))


    def area(self):
        """Calculate the solvent accessible surface area and saves it to
        area.xvg. If the mode is set to affinity, only the wt protein structure
        ensemble will be used and the values for the interaction surface will
        be written into the .xvg file
        """
        gmx(['sasa', '-s', 'confout.gro'], input=b'0', **self.pipe)


    def schlitter(self, en):
        """Calculates an upper limit of the entropy according to Schlitter's
        formula. Used in .fullrun() if the mode is stability
        """
        trjcat = ['trjcat', '-cat', 'yes', '-f']
        covar = ['covar', '-f', 'trajout.xtc', '-nopbc', '-s']
        anaeig = ['anaeig', '-v', 'eigenvec.trr', '-entropy', '-s']

        trrs = [self.maindir+'/'+en+'/%d/traj.trr' % (n+1)
            for n in range(len(self))]

        gmx(trjcat+trrs, **self.pipe)
        gmx(
            covar+[self.maindir+'/'+en+"/topol.tpr"],
            input=self.input['covar'],
            **self.pipe
        )
        entropy = gmx(
            anaeig + [self.maindir+'/'+en+"/topol.tpr"],
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        log('entropy.log', entropy)

        if self.pipe['stdout'] == None:
            print(entropy.stdout.decode('utf-8'))



class ResumeCheckpoint_affinity(ResumeCheckpoint_stability):
    """Subclassed from ResumeCheckpoint_stability to add additional procedures to calculate
    the affinity changes in mutated proteins and restarts energy calculations
    """
    def __init__(
        self,
        wtpdb,
        mutlist,
        flags,
        chaingrp,
        spmdp,
        ckpt,
        dummy,
        verbosity=0,
    ):
        self.grp1 = chaingrp
        cmd.load(wtpdb)
        self.chains = cmd.get_chains()
        self.grp2 = "".join([c for c in cmd.get_chains() if c not in chaingrp])
        cmd.reinitialize()
        super().__init__(
           wtpdb=wtpdb,
           mutlist=mutlist,
           flags=flags,
           spmdp=spmdp,
           ckpt = ckpt,
           verbosity=verbosity,
           dummy=dummy
        )


    def split_chains(self, d):
        """Split the .pdb file into two new .pdb files as specified in the
        chaingrp argument. only one group needs to be specified. The leftover
        chains automatically form the second group.
        """
        pdb = d.split('/')[-1]
        cmd.load(pdb+'.pdb')
        cmd.split_chains()
        save1 = ', '.join([pdb+'_'+i for i in self.grp1])
        save2 = ', '.join([pdb+'_'+i for i in self.grp2])
        cmd.save(self.grp1+'.pdb', save1)
        cmd.save(self.grp2+'.pdb', save2)
        cmd.reinitialize()


    def do_minimization_chains(self):
        """Go into all the directories and minimize the .pdb files of the
        unbounded proteins instead.
        """
        fn = self.grp1
        gmx(
            ['pdb2gmx'] + self.flags['pdb2gmx'] + [
                '-f', fn+'.pdb', '-o', fn+'.gro', '-p', fn + '_topol.top'
            ],
            **self.pipe
        )
        gmx(
            ['editconf'] + self.flags['editconf'] + [
                '-f', fn+'.gro', '-o', fn+'.gro'
            ],
            **self.pipe,
            input=self.input['editconf']
        )
        gmx(
            ['grompp'] + self.flags['grompp'] + [
                '-c', fn+'.gro', '-o', fn+'.tpr', '-p', fn + '_topol.top'
            ],
            **self.pipe,
            input=self.input['grompp']
        )
        gmx(
            ['mdrun'] + self.flags['mdrun'] + ['-deffnm', fn],
            **self.pipe,
            input=self.input['mdrun']
        )

        fn = self.grp2
        gmx(
            ['pdb2gmx'] + self.flags['pdb2gmx'] + [
                '-f', fn+'.pdb', '-o', fn+'.gro', '-p', fn + '_topol.top'
            ],
            **self.pipe
        )
        gmx(
            ['editconf'] + self.flags['editconf'] + [
                '-f', fn+'.gro', '-o', fn+'.gro'
            ],
            **self.pipe,
            input=self.input['editconf']
        )
        gmx(
            ['grompp'] + self.flags['grompp'] + [
                '-c', fn+'.gro', '-o', fn+'.tpr', '-p', fn + '_topol.top'
            ],
            **self.pipe,
            input=self.input['grompp']
        )
        gmx(
            ['mdrun'] + self.flags['mdrun'] + ['-deffnm', fn],
            **self.pipe,
            input=self.input['mdrun']
        )


    def single_point_chains(self):
        """Creates a single point .tpr file of the single groups.
        """
        gromppflags = self.flags['grompp'].copy()
        idx = gromppflags.index('-f')
        gromppflags.pop(idx)
        gromppflags.pop(idx)
        gmx(
            [
                'grompp', '-f', self.spmdp,
                '-c', self.grp1+'.gro',
                '-p', self.grp1+'_topol.top',
                '-o', self.grp1+'_sp.tpr',
            ] + gromppflags,
            **self.pipe
        )
        gmx(
            [
                'grompp', '-f', self.spmdp,
                '-c', self.grp2+'.gro',
                '-p', self.grp2+'_topol.top',
                '-o', self.grp2+'_sp.tpr',
            ] + gromppflags,
            **self.pipe
        )


    def electrostatics_chains(self):
        """Calcutlate the Coulomb and Solvation Energy based on the single
        point .tpr files of the chain groups. Parameters are stored in a
        separate file for gropbe. Reference it through the main parameter file
        for CC/PBSA.
        """
        chainselec = ",".join(str(i) for i in range(len(self.grp1)))

        shutil.copy(self.flags['gropbe'][0], 'gropbe.prm')

        with open('gropbe.prm', 'a') as params:
            params.write("in(tpr,%s_sp.tpr)" % self.grp1)

        while True:
            try:
                with open('/data/dist/gromacs_2019/lib/libgromacs.so.4', 'r') as f:
                    f.close()
                    print('shared library was accessible')
            except IOError:
                print('library could not be accessed')
                time.sleep(120)
                continue
            break

        gropbe = subprocess.run(
            ["/data/tom/GroPBS-Make-3/./gropbe", 'gropbe.prm'],
            input=bytes(chainselec, 'utf-8'),
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        log("%s_solvation.log" % self.grp1, gropbe)

        if self.pipe['stdout'] == None:
            print(gropbe.stdout.decode('utf-8'))
        
        chainselec = ",".join(str(i) for i in range(len(self.grp2)))

        shutil.copy(self.flags['gropbe'][0], 'gropbe.prm')

        with open('gropbe.prm', 'a') as params:
            params.write("in(tpr,%s_sp.tpr)" % self.grp2)
        
        while True:
            try:
                with open('/data/dist/gromacs_2019/lib/libgromacs.so.4', 'r') as f:
                    f.close()
                    print('shared library was accessible')
            except IOError:
                print('library could not be accessed')
                time.sleep(120)
                continue
            break

        gropbe = subprocess.run(
            ["/data/tom/GroPBS-Make-3/./gropbe", 'gropbe.prm'],
            input=bytes(chainselec, 'utf-8'),
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        log("%s_solvation.log" % self.grp2, gropbe)

        if self.pipe['stdout'] == None:
            print(gropbe.stdout.decode('utf-8'))


    def lj_chains(self):
        """Calculate the Lennard-Jones Energy based on the sp.tpr of the
        unbound proteins
        """
        gmx([
            'mdrun', '-s', self.grp1+'_sp.tpr',
            '-rerun', self.grp1+'.gro',
            '-deffnm', self.grp1+'_sp',
            '-nt', '1'
        ])
        lj = gmx(
            ['energy', '-f', self.grp1+'_sp.edr', '-sum', 'yes'],
            input=b'5 7',
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        lj.stderr = None
        log(self.grp1+"_lj.log", lj)

        if self.pipe['stdout'] == None:
            print(lj.stdout.decode('utf-8'))

        gmx([
            'mdrun', '-s', self.grp2+'_sp.tpr',
            '-rerun', self.grp2+'.gro',
            '-deffnm', self.grp2+'_sp',
            '-nt', '1'
        ])
        lj = gmx(
            ['energy', '-f', self.grp2+'_sp.edr', '-sum', 'yes'],
            input=b'5 7',
            stdout=subprocess.PIPE,
            stderr=self.pipe['stderr']
        )
        lj.stderr = None
        log("".join(self.grp2)+"_lj.log", lj)

        if self.pipe['stdout'] == None:
            print(lj.stdout.decode('utf-8'))


    def area(self):
        """Calculate the interaction area of the wildtype protein.
        """
        sasa = ['sasa', '-s']

        os.chdir(self.wt)

        if self.n > 0:

            for i in range(1, len(self)+1):
                os.chdir(str(i))
                if os.path.isfile('area.xvg'):
                    pass
                else:
                    gmx(sasa + ['confout.gro'], input=b'0')

                if os.path.isfile(self.grp1+'_area.xvg'):
                    pass
                else:
                    gmx(
                    sasa + [self.grp1 + '.gro', '-o', self.grp1+'_area.xvg'],
                    input=b'0',
                    **self.pipe
                    )

                if os.path.isfile(self.grp2+'_area.xvg'):
                    pass
                else:
                    gmx(
                    sasa + [self.grp2 + '.gro', '-o', self.grp2+'_area.xvg'],
                    input=b'0',
                    **self.pipe
                    )
                os.chdir('..')

        else: 
            gmx(sasa + ['confout.gro'], input=b'0')
            gmx(
                sasa + [self.grp1 + '.gro', '-o', self.grp1+'_area.xvg'],
                input=b'0',
                **self.pipe
            )
            gmx(
                sasa + [self.grp2 + '.gro', '-o', self.grp2+'_area.xvg'],
                input=b'0',
                **self.pipe
            )

        os.chdir(self.maindir)


